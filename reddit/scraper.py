import requests
import time
import datetime
import os

from db.reader import is_already_processed
from db.writer import insert_post
from reddit.discovery import discover_adjacent_subreddits
from config.config_loader import get_config
from utils.logger import setup_logger
from utils.helpers import load_json, save_json, truncate

log = setup_logger()
config = get_config()

BASE_URL = "https://www.reddit.com"
# Reddit blocks generic User-Agent strings; use a descriptive one.
HEADERS = {"User-Agent": "emotional-trend-miner/1.0 (non-commercial research tool)"}
EXPLORATORY_FILE = "data/exploratory_subreddits.json"
REQUEST_DELAY = config["scraper"].get("request_delay_seconds", 2)


def _get(url: str, params: dict = None, retries: int = 3) -> dict | None:
    """HTTP GET with exponential-backoff retry."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                log.warning(f"Rate limited by Reddit. Waiting {wait}s...")
                time.sleep(wait)
            elif resp.status_code in (403, 404):
                log.warning(f"HTTP {resp.status_code} for {url} — skipping")
                return None
            else:
                log.warning(f"HTTP {resp.status_code} for {url} (attempt {attempt + 1}/{retries})")
                time.sleep(2 * (2 ** attempt))
        except requests.RequestException as e:
            log.error(f"Request error (attempt {attempt + 1}/{retries}): {e}")
            time.sleep(2 * (2 ** attempt))
    return None


def _is_in_age_range(created_utc: float, min_days: int, max_days: int) -> bool:
    age_days = (datetime.datetime.utcnow() - datetime.datetime.utcfromtimestamp(created_utc)).days
    return min_days <= age_days <= max_days


def _parse_post(data: dict, subreddit_name: str) -> dict:
    return {
        "id":           data["id"],
        "title":        data.get("title", ""),
        "body":         data.get("selftext", ""),
        "score":        data.get("score", 0),
        "num_comments": data.get("num_comments", 0),
        "created_utc":  data["created_utc"],
        "subreddit":    subreddit_name,
        "url":          f"{BASE_URL}{data['permalink']}",
        "type":         "post",
    }


def _fetch_comments(post: dict, max_comments: int = 10) -> list:
    """Fetch top-level comments for a post via the public JSON API."""
    url = f"{BASE_URL}/r/{post['subreddit']}/comments/{post['id']}.json"
    data = _get(url, params={"limit": max_comments, "depth": 1, "sort": "top"})
    if not data or len(data) < 2:
        return []

    comments = []
    for child in data[1].get("data", {}).get("children", []):
        if child.get("kind") != "t1":
            continue
        c = child["data"]
        body = c.get("body", "")
        if not body or body in ("[deleted]", "[removed]"):
            continue
        if is_already_processed(c["id"]):
            continue
        comments.append({
            "id":            c["id"],
            "title":         post["title"],
            "body":          body,
            "post_body":     post["body"],
            "score":         c.get("score", 0),
            "num_comments":  0,
            "created_utc":   c.get("created_utc", post["created_utc"]),
            "subreddit":     post["subreddit"],
            "url":           f"{BASE_URL}{c.get('permalink', '')}",
            "type":          "comment",
            "parent_post_id": post["id"],
        })
    return comments


def fetch_posts_from_subreddit(subreddit_name: str, limit: int = 100) -> list:
    min_days = config["scraper"]["min_post_age_days"]
    max_days  = config["scraper"]["max_post_age_days"]
    include_comments = config["scraper"].get("include_comments", False)
    results  = []
    seen_ids = set()

    for feed in ("new", "hot"):
        url   = f"{BASE_URL}/r/{subreddit_name}/{feed}.json"
        after = None
        feed_fetched = 0
        log.info(f"  r/{subreddit_name}/{feed} — requesting up to {limit} posts")

        while feed_fetched < limit:
            params = {"limit": min(100, limit - feed_fetched), "raw_json": 1}
            if after:
                params["after"] = after

            data = _get(url, params=params)
            if not data:
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                post_data = child.get("data", {})
                post_id   = post_data.get("id")
                if not post_id or post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                if not _is_in_age_range(post_data["created_utc"], min_days, max_days):
                    continue
                if is_already_processed(post_id):
                    continue

                post = _parse_post(post_data, subreddit_name)
                results.append(post)

                if include_comments:
                    time.sleep(REQUEST_DELAY)
                    results.extend(_fetch_comments(post))

            after = data.get("data", {}).get("after")
            feed_fetched += len(children)
            if not after:
                break

            time.sleep(REQUEST_DELAY)  # between pagination requests

        time.sleep(REQUEST_DELAY)  # between feeds

    log.info(f"  r/{subreddit_name}: {len(results)} items collected")
    return results


def get_exploratory_subreddits() -> list:
    if not os.path.exists(EXPLORATORY_FILE):
        return []
    data = load_json(EXPLORATORY_FILE)
    last_updated = data.get("last_updated", "")
    refresh_days = config["subreddits"]["exploratory_refresh_days"]
    if not last_updated or (
        datetime.datetime.utcnow() - datetime.datetime.fromisoformat(last_updated)
    ).days >= refresh_days:
        log.info("Exploratory subreddit list needs refresh")
        return []
    return data.get("subreddits", [])


def update_exploratory_subreddits(new_subreddits: list):
    data = {
        "last_updated": datetime.datetime.utcnow().isoformat(),
        "subreddits":   new_subreddits,
    }
    os.makedirs("data", exist_ok=True)
    save_json(data, EXPLORATORY_FILE)
    log.info(f"Updated exploratory subreddits: {', '.join(new_subreddits)}")


def scrape_subreddits() -> list:
    """Scrape configured primary (and optionally exploratory) subreddits."""
    primary_subreddits  = config["subreddits"]["primary"]
    primary_pct         = config["subreddits"]["primary_percentage"]
    exploratory_pct     = config["subreddits"]["exploratory_percentage"]
    exploratory_limit   = config["subreddits"]["exploratory_limit"]
    exploratory_enabled = config["subreddits"].get("exploratory_enabled", True)

    total_limit              = config["scraper"]["max_items_per_day"]
    primary_limit            = int((primary_pct / 100) * total_limit)
    exploratory_limit_posts  = int((exploratory_pct / 100) * total_limit)

    per_primary = max(1, primary_limit // len(primary_subreddits))
    log.info(f"Scraping {len(primary_subreddits)} primary subreddits ({per_primary} posts/sub)...")

    all_posts = []
    for sub in primary_subreddits:
        posts = fetch_posts_from_subreddit(sub, limit=per_primary)
        for post in posts:
            insert_post(post, community_type="primary")
        all_posts.extend(posts)

    if exploratory_enabled:
        exploratory_subreddits = get_exploratory_subreddits()
        if not exploratory_subreddits:
            if all_posts:
                log.info("Discovering new exploratory subreddits...")
                summaries = [truncate(f"{p['title']} {p['body']}", 300) for p in all_posts[:10]]
                suggestions = discover_adjacent_subreddits(summaries)
                exploratory_subreddits = [s["subreddit"] for s in suggestions][:exploratory_limit]
                update_exploratory_subreddits(exploratory_subreddits)
            else:
                log.warning("No primary posts found to discover exploratory subreddits")

        if exploratory_subreddits:
            per_exploratory = max(1, exploratory_limit_posts // len(exploratory_subreddits))
            log.info(f"Scraping {len(exploratory_subreddits)} exploratory subreddits...")
            for sub in exploratory_subreddits:
                posts = fetch_posts_from_subreddit(sub, limit=per_exploratory)
                for post in posts:
                    insert_post(post, community_type="exploratory")
                all_posts.extend(posts)
    else:
        log.info("Exploratory subreddit discovery is disabled (exploratory_enabled: false)")

    log.info(f"Total items scraped: {len(all_posts)}")
    return all_posts
