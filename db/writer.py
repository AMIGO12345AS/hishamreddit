import sqlite3
from config.config_loader import get_config
from datetime import datetime, UTC
from pathlib import Path

config = get_config()
DB_PATH = config["database"]["path"]

_conn = None

def _get_connection():
    global _conn
    if _conn is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn

def insert_post(post: dict, community_type: str = "primary"):
    conn = _get_connection()
    try:
        conn.execute("""
        INSERT OR IGNORE INTO posts (
            id, url, title, body, subreddit, created_utc, last_active,
            processed_at, community_type, type, post_body, parent_post_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post["id"],
            post["url"],
            post["title"],
            post.get("body", ""),
            post["subreddit"],
            post["created_utc"],
            post["created_utc"],
            datetime.now(UTC).date().isoformat(),
            community_type,
            post.get("type", "post"),
            post.get("post_body", ""),
            post.get("parent_post_id")
        ))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite Insert Error] {e}")

def mark_posts_in_history(post_ids: list[str]):
    """Bulk-insert post IDs into the history table after AI processing succeeds."""
    conn = _get_connection()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO history (id, processed_at) VALUES (?, ?)",
            [(pid, datetime.now(UTC).isoformat()) for pid in post_ids]
        )
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite mark_posts_in_history Error] {e}")

def update_post_filter_scores(post_id: str, scores: dict):
    """Update filtering phase scores.

    Column mapping (original name -> current semantic meaning):
      implementability_score -> relatability_score
      technical_depth_score  -> content_potential_score
    """
    conn = _get_connection()
    try:
        conn.execute("""
        UPDATE posts SET
            relevance_score = ?,
            emotion_score = ?,
            pain_score = ?,
            implementability_score = ?,
            technical_depth_score = ?,
            processed_at = ?
        WHERE id = ?
        """, (
            scores.get("relevance_score"),
            scores.get("emotional_intensity"),
            scores.get("pain_point_clarity"),
            scores.get("relatability_score"),       # stored in implementability_score column
            scores.get("content_potential_score"),  # stored in technical_depth_score column
            datetime.now(UTC).date().isoformat(),
            post_id
        ))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite update_post_filter_scores Error] {e}")

def update_post_insight(post_id: str, insight: dict):
    """Update content intelligence fields from deep insight analysis.

    Column mapping (original name -> current semantic meaning):
      tags       -> topic  (e.g. 'male loneliness')
      roi_weight -> pain_score (1-10)
    """
    conn = _get_connection()
    cursor = conn.cursor()

    fields = {
        "tags": insight.get("topic"),              # repurpose tags column for topic
        "roi_weight": insight.get("pain_score"),   # repurpose roi_weight for pain_score
        "emotion_label": insight.get("emotion"),
        "summary": insight.get("summary"),
        "viral_hook": insight.get("viral_hook"),
        "content_angle": insight.get("content_angle"),
        "controversy_score": insight.get("controversy_score"),
    }

    updates = [f"{key} = ?" for key, value in fields.items() if value is not None]
    values = [value for value in fields.values() if value is not None]

    if not updates:
        return

    updates.append("insight_processed = 1")
    updates.append("insight_processed_at = ?")
    values.append(datetime.utcnow().isoformat())

    query = f"""
        UPDATE posts SET {', '.join(updates)}
        WHERE id = ?
    """
    try:
        cursor.execute(query, values + [post_id])
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite update_post_insight Error] {e}")

def mark_insight_processed(post_id: str):
    """Mark a post as having been processed for deep insight."""
    conn = _get_connection()
    try:
        conn.execute("""
        UPDATE posts SET insight_processed = 1
        WHERE id = ?
        """, (post_id,))
        conn.commit()
    except sqlite3.Error as e:
        print(f"[SQLite mark_insight_processed Error] {e}")
