import json
from typing import List, Dict, Any
from utils.helpers import estimate_tokens, sanitize_text
from utils.logger import setup_logger
from config.config_loader import get_config, PROMPT_INSIGHT

log = setup_logger()
config = get_config()


def _format_post_content(post: dict) -> str:
    post_body = post.get("post_body", "")
    if post_body:
        return (
            f"Post title: {post['title']}\n"
            f"Post body: {post_body}\n"
            f"Comment: {post['body']}"
        )
    return f"Post title: {post['title']}\nPost body: {post['body']}"


def build_insight_prompt(post: dict) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a content intelligence analyst specializing in male psychology, self-improvement communities, and digital content strategy."
        },
        {
            "role": "user",
            "content": f"{config['prompts'][PROMPT_INSIGHT]}\n\n{_format_post_content(post)}"
        }
    ]


def run_insight(post: dict) -> dict | None:
    """Phase-2 deep analysis: extract content intelligence for a single post.
    Returns an insight dict or None if parsing fails.
    """
    from gpt.client import chat_complete
    title = sanitize_text(post.get("title", ""))
    body = sanitize_text(post.get("body", ""))
    post_body = sanitize_text(post.get("post_body", ""))
    messages = build_insight_prompt({"title": title, "body": body, "post_body": post_body})
    model = config["ai"]["model_deep"]
    max_tokens = config["ai"].get("max_tokens_per_post", 1000)
    content = chat_complete(messages, model, max_tokens=max_tokens)
    return json.loads(content)


# ---- kept for reference, not used in sequential mode ----

def prepare_insight_batch(posts: List[dict]) -> List[Dict[str, Any]]:
    model = config["ai"].get("model_deep", "gpt-4o")
    payload = []
    for post in posts:
        title = sanitize_text(post.get("title", ""))
        body = sanitize_text(post.get("body", ""))
        if not title or not body:
            continue
        post_body = sanitize_text(post.get("post_body", ""))
        messages = build_insight_prompt({"title": title, "body": body, "post_body": post_body})
        payload.append({
            "id": post["id"],
            "messages": messages,
            "meta": {"estimated_tokens": estimate_tokens(title + body + post_body, model)}
        })
    return payload
