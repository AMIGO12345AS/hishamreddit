"""
Reddit public JSON API fetcher (no authentication required).
Uses Reddit's built-in JSON endpoint: https://www.reddit.com/r/{subreddit}/{sort}.json
"""
import requests
import time
import datetime
from typing import List, Dict, Any
from utils.logger import setup_logger

log = setup_logger()

# User-Agent (Reddit API best practice, even for public access)
USER_AGENT = "hishamreddit-scraper/1.0"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def fetch_subreddit_posts(
    subreddit_name: str,
    sort: str = "top",
    time_filter: str = "month",
    limit: int = 100,
    timeout: int = 10,
    delay: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Fetch posts from a subreddit using public Reddit JSON endpoint.
    
    Args:
        subreddit_name: name of subreddit (without r/)
        sort: 'top', 'hot', 'new', 'rising', etc.
        time_filter: 'day', 'week', 'month', 'year', 'all' (only for 'top')
        limit: max posts to fetch (Reddit typically returns ~25-100 per call)
        timeout: request timeout in seconds
        delay: delay in seconds before request (Reddit-friendly)
    
    Returns:
        List of post dicts with keys: id, title, selftext, created_utc, subreddit, 
        permalink, url, score, num_comments, hours_old, is_fresh
    """
    if delay > 0:
        time.sleep(delay)
    
    posts = []
    
    try:
        # Build URL based on sort method
        if sort == "top":
            url = f"https://www.reddit.com/r/{subreddit_name}/{sort}.json?t={time_filter}&limit={limit}"
        else:
            url = f"https://www.reddit.com/r/{subreddit_name}/{sort}.json?limit={limit}"
        
        log.debug(f"Fetching {sort} posts from r/{subreddit_name}: {url}")
        
        response = SESSION.get(url, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        children = data.get("data", {}).get("children", [])
        
        now_utc = datetime.datetime.utcnow()
        
        for child in children:
            post_data = child.get("data", {})
            created_utc = post_data.get("created_utc", 0)
            created_dt = datetime.datetime.utcfromtimestamp(created_utc)
            hours_old = (now_utc - created_dt).total_seconds() / 3600
            is_fresh = hours_old < 24  # Posts younger than 24 hours
            
            posts.append({
                "id": post_data.get("id"),
                "title": post_data.get("title", ""),
                "selftext": post_data.get("selftext", ""),
                "created_utc": created_utc,
                "created_dt": created_dt.isoformat(),
                "hours_old": round(hours_old, 1),
                "is_fresh": is_fresh,
                "subreddit": post_data.get("subreddit", ""),
                "permalink": post_data.get("permalink", ""),
                "url": f"https://www.reddit.com{post_data.get('permalink', '')}",
                "score": post_data.get("score", 0),
                "num_comments": post_data.get("num_comments", 0),
                "upvote_ratio": post_data.get("upvote_ratio", 0.5),
            })
        
        log.info(f"✓ Fetched {len(posts)} posts from r/{subreddit_name} ({sort})")
        return posts
    
    except requests.exceptions.Timeout:
        log.error(f"✗ Timeout fetching r/{subreddit_name} ({sort})")
        return []
    except requests.exceptions.HTTPError as e:
        log.error(f"✗ HTTP {e.response.status_code} from r/{subreddit_name} ({sort}): {e}")
        return []
    except Exception as e:
        log.error(f"✗ Error fetching r/{subreddit_name} ({sort}): {str(e)}")
        return []


def fetch_comments(post_id: str, subreddit_name: str, timeout: int = 10, delay: float = 0.0) -> List[Dict[str, Any]]:
    """
    Fetch top-level comments from a post using public Reddit JSON endpoint.
    
    Args:
        post_id: Reddit post ID (without 't3_' prefix)
        subreddit_name: subreddit name
        timeout: request timeout in seconds
        delay: delay in seconds before request
    
    Returns:
        List of comment dicts with keys: id, body, created_utc, score, author, hours_old, is_fresh
    """
    if delay > 0:
        time.sleep(delay)
    
    comments = []
    
    try:
        url = f"https://www.reddit.com/r/{subreddit_name}/comments/{post_id}.json?limit=100"
        log.debug(f"Fetching comments for post {post_id}")
        
        response = SESSION.get(url, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        now_utc = datetime.datetime.utcnow()
        
        # The response is a list: [post_data, comments_data]
        if len(data) > 1:
            comments_data = data[1].get("data", {}).get("children", [])
            
            for child in comments_data:
                if child.get("kind") == "t1":  # Comment (t1), not MoreComments (more)
                    comment_data = child.get("data", {})
                    created_utc = comment_data.get("created_utc", 0)
                    created_dt = datetime.datetime.utcfromtimestamp(created_utc)
                    hours_old = (now_utc - created_dt).total_seconds() / 3600
                    is_fresh = hours_old < 24
                    
                    comments.append({
                        "id": comment_data.get("id"),
                        "body": comment_data.get("body", ""),
                        "created_utc": created_utc,
                        "created_dt": created_dt.isoformat(),
                        "hours_old": round(hours_old, 1),
                        "is_fresh": is_fresh,
                        "score": comment_data.get("score", 0),
                        "author": comment_data.get("author", "[deleted]"),
                    })
        
        log.info(f"✓ Fetched {len(comments)} comments from post {post_id}")
        return comments
    
    except requests.exceptions.Timeout:
        log.error(f"✗ Timeout fetching comments for post {post_id}")
        return []
    except requests.exceptions.HTTPError as e:
        log.error(f"✗ HTTP {e.response.status_code} fetching comments: {e}")
        return []
    except Exception as e:
        log.error(f"✗ Error fetching comments: {str(e)}")
        return []

