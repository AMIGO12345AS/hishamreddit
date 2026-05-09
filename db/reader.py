import sqlite3
from config.config_loader import get_config
from utils.logger import setup_logger

log = setup_logger()
config = get_config()
DB_PATH = config["database"]["path"]

_conn = None

def _get_connection():
    global _conn
    if _conn is None:
        from pathlib import Path
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn

def is_already_processed(post_id: str) -> bool:
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM history WHERE id = ?", (post_id,)
        ).fetchone()
        return row is not None
    except sqlite3.Error as e:
        log.error(f"[SQLite is_already_processed Error] {e}")
        return False

def get_all_posts_by_tag(tag: str) -> list:
    """Retrieve posts matching a topic/tag, ordered by most recent."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM posts WHERE tags LIKE ? ORDER BY processed_at DESC",
            (f"%{tag}%",)
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        log.error(f"[SQLite get_all_posts_by_tag Error] {e}")
        return []

def get_posts_by_ids(post_ids: set, require_unprocessed: bool = False) -> list:
    if not post_ids:
        return []
    conn = _get_connection()
    try:
        placeholders = ",".join("?" * len(post_ids))
        query = f"SELECT * FROM posts WHERE id IN ({placeholders})"
        if require_unprocessed:
            query += " AND (insight_processed IS NULL OR insight_processed = 0)"
        rows = conn.execute(query, list(post_ids)).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        log.error(f"[SQLite get_posts_by_ids Error] {e}")
        return []

def get_post_parent_mapping(post_ids: set) -> dict:
    if not post_ids:
        return {}
    conn = _get_connection()
    try:
        placeholders = ",".join("?" * len(post_ids))
        rows = conn.execute(
            f"SELECT id, parent_post_id FROM posts WHERE id IN ({placeholders})",
            list(post_ids)
        ).fetchall()
        return {row["id"]: row["parent_post_id"] for row in rows}
    except sqlite3.Error as e:
        log.error(f"[SQLite get_post_parent_mapping Error] {e}")
        return {}

def get_top_insights_from_today(limit: int = 10) -> list:
    """Return today's top posts ordered by content potential, emotional intensity, and pain score.

    Column mapping:
      technical_depth_score -> content_potential_score
      emotion_score         -> emotional_intensity
      roi_weight            -> pain_score
    """
    conn = _get_connection()
    try:
        from datetime import datetime, UTC
        today = datetime.now(UTC).date().isoformat()
        rows = conn.execute(
            """
            SELECT * FROM posts
            WHERE insight_processed = 1
              AND processed_at = ?
            ORDER BY technical_depth_score DESC, emotion_score DESC, roi_weight DESC
            LIMIT ?
            """,
            (today, limit)
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        log.error(f"[SQLite get_top_insights_from_today Error] {e}")
        return []
