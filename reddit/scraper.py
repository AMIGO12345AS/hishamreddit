import datetime
import os
import time

from db.reader import is_already_processed
from db.writer import insert_post
from reddit.discovery import discover_adjacent_subreddits
from reddit.fetcher import fetch_subreddit_posts, fetch_comments
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import load_json, save_json, truncate
from reddit.rate_limiter import RedditRateLimiter

log = setup_logger()
config = get_config()

# Initialize rate limiter and config params
limiter = RedditRateLimiter(config["scraper"].get("rate_limit_per_minute", 60))
EXPLORATORY_FILE = "data/exploratory_subreddits.json"

# New config params with defaults
POSTS_PER_FEED = config["scraper"].get("posts_per_feed", 50)
TOTAL_POSTS_PER_SUBREDDIT = config["scraper"].get("total_posts_per_subreddit", 100)
COMMENTS_PER_POST = config["scraper"].get("comments_per_post", 25)
REQUEST_DELAY = config["scraper"].get("request_delay_seconds", 0.5)
MIN_POST_SCORE = config["scraper"].get("min_post_score", 1)
MIN_COMMENT_SCORE = config["scraper"].get("min_comment_score", 1)
PREFER_FRESH_HOURS = config["scraper"].get("prefer_fresh_hours", 24)

def calculate_engagement_score(post: dict) -> float:
    """
    Calculate post engagement score (0-1) combining freshness + activity.
    Higher score = more valuable for analysis.
    """
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)
    upvote_ratio = post.get("upvote_ratio", 0.5)
    hours_old = post.get("hours_old", 0)
    
    # Engagement metrics
    comment_weight = min(comments / 100, 1.0)  # Cap at 100 comments
    upvote_weight = min(score / 500, 1.0)      # Cap at 500 upvotes
    
    # Freshness boost (recent posts get bonus)
    freshness_boost = 1.5 if post.get("is_fresh") else 1.0
    
    # Recency decay (older posts have lower score)
    decay = max(0.1, 1.0 - (hours_old / 168))  # 0.1-1.0 over 1 week
    
    engagement = (comment_weight * 0.4 + upvote_weight * 0.6) * decay * freshness_boost
    return round(min(engagement, 1.0), 3)


def fetch_posts_from_subreddit(subreddit_name: str) -> list:
    """
    Fetch HIGH VOLUME posts from subreddit using all feeds (top/hot/new).
    Prioritizes fresh + high-engagement posts for emotional trend analysis.
    """
    min_days = config["scraper"].get("min_post_age_days", 0)
    max_days = config["scraper"].get("max_post_age_days", 7)
    include_comments = config["scraper"].get("include_comments", True)
    results = []
    seen_ids = set()

    post_skip_seen = 0
    post_skip_age = 0
    post_skip_score = 0
    post_skip_dupl = 0
    post_remaining = 0
    comment_fetched = 0
    comment_skip_seen = 0
    comment_skip_score = 0
    comment_skip_dupl = 0
    comment_remaining = 0

    try:
        log.info(f"Fetching posts from r/{subreddit_name} (target: {TOTAL_POSTS_PER_SUBREDDIT} posts)...")
        combined = []
        
        # Fetch from all feeds with high volume
        feeds = [
            ("top", "week"),      # Top posts this week (high engagement)
            ("hot", None),        # Currently trending
            ("new", None),        # Fresh posts (emotional immediacy)
        ]
        
        for sort_method, time_filter in feeds:
            limiter.wait()
            posts = fetch_subreddit_posts(
                subreddit_name,
                sort=sort_method,
                time_filter=time_filter,
                limit=POSTS_PER_FEED,
                delay=REQUEST_DELAY
            )
            combined.extend(posts)

        log.info(f"Raw posts fetched from r/{subreddit_name}: {len(combined)}")
        
        # De-duplicate by ID and score by engagement + freshness
        post_dict = {}
        for post in combined:
            post_id = post["id"]
            if post_id not in post_dict:
                post["engagement_score"] = calculate_engagement_score(post)
                post_dict[post_id] = post
        
        # Sort by engagement score (highest first)
        sorted_posts = sorted(post_dict.values(), key=lambda p: p["engagement_score"], reverse=True)
        
        # Take top posts up to target
        sorted_posts = sorted_posts[:TOTAL_POSTS_PER_SUBREDDIT]
        
        log.info(f"De-duplicated & ranked: {len(sorted_posts)} unique posts from r/{subreddit_name}")
        start_time = time.time()

        for i, post in enumerate(sorted_posts):
            if i % 10 == 0:
                log.info(f"Processing post #{i+1}/{len(sorted_posts)} (engagement: {post.get('engagement_score', 0)})")

            if post["id"] in seen_ids:
                post_skip_seen += 1
                continue
            seen_ids.add(post["id"])

            created_at = datetime.datetime.fromisoformat(post.get("created_dt", ""))
            age_days = (datetime.datetime.utcnow() - created_at).days
            
            log.debug(f"Post {post['id']} | {post.get('hours_old', '?')}h old | {post['score']} upvotes | {post['num_comments']} comments — {post['title'][:50]}")

            if not (min_days <= age_days <= max_days):
                post_skip_age += 1
                continue
            if post["score"] < MIN_POST_SCORE:
                post_skip_score += 1
                continue
            if is_already_processed(post["id"]):
                post_skip_dupl += 1
                continue

            results.append({
                "id": post["id"],
                "title": post["title"],
                "body": post["selftext"],
                "created_utc": post["created_utc"],
                "hours_old": post.get("hours_old", 0),
                "subreddit": subreddit_name,
                "url": post["url"],
                "score": post["score"],
                "num_comments": post["num_comments"],
                "engagement_score": post.get("engagement_score", 0),
                "type": "post"
            })
            post_remaining += 1

            if include_comments and post["num_comments"] > 0:
                try:
                    limiter.wait()
                    comments_list = fetch_comments(
                        post["id"],
                        subreddit_name,
                        delay=REQUEST_DELAY
                    )
                    
                    # Sort by score, take top comments
                    comments_list = sorted(comments_list, key=lambda c: c.get("score", 0), reverse=True)[:COMMENTS_PER_POST]
                    comment_fetched += len(comments_list)
                    
                    for comment in comments_list:
                        if comment["id"] in seen_ids:
                            comment_skip_seen += 1
                            continue
                        seen_ids.add(comment["id"])

                        if comment["score"] < MIN_COMMENT_SCORE:
                            comment_skip_score += 1
                            continue
                        if is_already_processed(comment["id"]):
                            comment_skip_dupl += 1
                            continue

                        results.append({
                            "id": comment["id"],
                            "title": post["title"],
                            "body": comment["body"],
                            "post_body": post["selftext"],
                            "created_utc": comment["created_utc"],
                            "hours_old": comment.get("hours_old", 0),
                            "subreddit": subreddit_name,
                            "url": f"https://www.reddit.com{post['permalink']}#{comment['id']}",
                            "score": comment["score"],
                            "author": comment.get("author", "[deleted]"),
                            "type": "comment",
                            "parent_post_id": post["id"],
                        })
                        comment_remaining += 1
                except Exception as e:
                    log.warning(f"Failed to fetch comments for post {post['id']}: {str(e)}")

        sum_fetched = len(sorted_posts) + comment_fetched
        sum_skip_seen = post_skip_seen + comment_skip_seen
        sum_skip_score = post_skip_score + comment_skip_score
        sum_skip_dupl = post_skip_dupl + comment_skip_dupl

        log.info(f"\n{'r/' + subreddit_name:<25} | {'Fetched':<12} | {'Skip (seen)':<12} | {'Skip (age)':<12} | {'Skip (score)':<12} | {'Skip (dup)':<12} | {'Remaining':<12}")
        log.info(f"{'Posts':<25} | {len(sorted_posts):<12} | {post_skip_seen:<12} | {post_skip_age:<12} | {post_skip_score:<12} | {post_skip_dupl:<12} | {post_remaining:<12}")
        log.info(f"{'Comments':<25} | {comment_fetched:<12} | {comment_skip_seen:<12} | {'-':<12} | {comment_skip_score:<12} | {comment_skip_dupl:<12} | {comment_remaining:<12}")
        log.info(f"{'Sum':<25} | {sum_fetched:<12} | {sum_skip_seen:<12} | {post_skip_age:<12} | {sum_skip_score:<12} | {sum_skip_dupl:<12} | {len(results):<12}\n")

    except Exception as e:
        log.error(f"Error fetching from r/{subreddit_name}: {str(e)}")

    log.info(f"Finished processing posts from r/{subreddit_name} in {time.time() - start_time:.2f} seconds")
    return results

def get_exploratory_subreddits():
    if not os.path.exists(EXPLORATORY_FILE):
        return []

    data = load_json(EXPLORATORY_FILE)
    last_updated = data.get("last_updated", "")
    refresh_days = config["subreddits"]["exploratory_refresh_days"]

    if not last_updated or (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(last_updated)).days >= refresh_days:
        log.info("Exploratory subreddit list needs refresh")
        return []

    return data.get("subreddits", [])


def update_exploratory_subreddits(new_subreddits):
    data = {
        "last_updated": datetime.datetime.utcnow().isoformat(),
        "subreddits": new_subreddits
    }
    os.makedirs("data", exist_ok=True)
    save_json(data, EXPLORATORY_FILE)
    log.info(f"Updated exploratory subreddits: {', '.join(new_subreddits)}")

def scrape_subreddits() -> list:
    """
    Scrapes all configured subreddits with HIGH VOLUME.
    Builds continuously accumulating emotional intelligence database.
    """
    primary_subreddits = config["subreddits"]["primary"]
    primary_pct = config["subreddits"]["primary_percentage"]
    exploratory_pct = config["subreddits"]["exploratory_percentage"]
    exploratory_limit = config["subreddits"]["exploratory_limit"]
    exploratory_enabled = config["subreddits"].get("exploratory_enabled", True)

    total_daily_limit = config["scraper"].get("max_items_per_day", 500)
    
    log.info(f"\n{'='*80}")
    log.info(f"REDDIT SCRAPER START - High Volume Mode")
    log.info(f"{'='*80}")
    log.info(f"Total daily limit: {total_daily_limit} posts")
    log.info(f"Posts per feed: {POSTS_PER_FEED}")
    log.info(f"Comments per post: {COMMENTS_PER_POST}")
    log.info(f"Request delay: {REQUEST_DELAY}s")
    log.info(f"Scraping {len(primary_subreddits)} primary subreddits...\n")
    
    primary_posts = []
    total_posts_collected = 0

    for idx, sub in enumerate(primary_subreddits, 1):
        log.info(f"[{idx}/{len(primary_subreddits)}] Scraping r/{sub}...")
        posts = fetch_posts_from_subreddit(sub)
        
        for post in posts:
            insert_post(post, community_type="primary")
        
        primary_posts.extend(posts)
        total_posts_collected += len(posts)
        
        if total_posts_collected >= total_daily_limit:
            log.warning(f"Reached daily limit ({total_daily_limit} posts). Stopping.")
            break

    if exploratory_enabled:
        log.info(f"\nExploring adjacent subreddits...")
        exploratory_subreddits = get_exploratory_subreddits()

        if not exploratory_subreddits:
            if primary_posts:
                log.info("Discovering new exploratory subreddits from trends...")
                summaries = [truncate(f"{p['title']} {p['body']}", 300) for p in primary_posts[:10]]
                suggestions = discover_adjacent_subreddits(summaries)
                exploratory_subreddits = [s["subreddit"] for s in suggestions][:exploratory_limit]
                update_exploratory_subreddits(exploratory_subreddits)
            else:
                log.warning("No primary posts found to discover exploratory subreddits")

        if exploratory_subreddits:
            log.info(f"Scraping {len(exploratory_subreddits)} exploratory subreddits...")
            for idx, sub in enumerate(exploratory_subreddits, 1):
                if total_posts_collected >= total_daily_limit:
                    break
                log.info(f"[exploratory {idx}/{len(exploratory_subreddits)}] Scraping r/{sub}...")
                posts = fetch_posts_from_subreddit(sub)
                for post in posts:
                    insert_post(post, community_type="exploratory")
                primary_posts.extend(posts)
                total_posts_collected += len(posts)
    else:
        log.info("Exploratory subreddit discovery is disabled (exploratory_enabled: false)")

    log.info(f"\n{'='*80}")
    log.info(f"SCRAPE COMPLETE")
    log.info(f"Total posts+comments collected: {len(primary_posts)}")
    log.info(f"Database: data/db.sqlite")
    log.info(f"{'='*80}\n")
    return primary_posts


if __name__ == "__main__":
    log.info("Starting Reddit scraper (no credentials needed - using public JSON API)...")
    results = scrape_subreddits()
    log.info(f"Scrape complete. Total posts retrieved: {len(results)}")
