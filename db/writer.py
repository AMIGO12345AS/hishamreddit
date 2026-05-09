def insert_post(post: dict, community_type: str = "primary"):
    """Stub: pretend to insert a post into database.
    For now just print a short summary so runs are visible.
    """
    print(f"[DB] Inserted {post.get('id')} ({post.get('type')}) into {community_type}")
