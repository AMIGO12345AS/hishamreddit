import json
from typing import List, Dict
from utils.helpers import estimate_tokens, sanitize_text
from utils.logger import setup_logger
from config.config_loader import get_config, PROMPT_FILTER

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


def build_filter_prompt(post: dict) -> List[Dict]:
    return [
        {
            "role": "system",
            "content": "You are an emotional content analyst identifying Reddit posts with genuine emotional depth, relatable struggles, and content potential for male self-improvement audiences."
        },
        {
            "role": "user",
            "content": f"{config['prompts'][PROMPT_FILTER]}\n\n{_format_post_content(post)}"
        }
    ]


def run_filter(post: dict) -> dict | None:
    """Phase-1 filter: score a single post via chat completion.
    Returns a scores dict or None if parsing fails.
    """
    from gpt.client import chat_complete
    title = sanitize_text(post.get("title", ""))
    body = sanitize_text(post.get("body", ""))
    post_body = sanitize_text(post.get("post_body", ""))
    messages = build_filter_prompt({"title": title, "body": body, "post_body": post_body})
    model = config["ai"]["model_filter"]
    max_tokens = config["ai"].get("max_tokens_per_post", 500)
    content = chat_complete(messages, model, max_tokens=max_tokens)
    return json.loads(content)


# ---- kept for reference, not used in sequential mode ----

def prepare_batch_payload(posts: List[dict]) -> List[Dict]:
    payload = []
    for post in posts:
        title = sanitize_text(post.get("title", ""))
        body = sanitize_text(post.get("body", ""))
        if not title or not body:
            continue
        post_body = sanitize_text(post.get("post_body", ""))
        messages = build_filter_prompt({"title": title, "body": body, "post_body": post_body})
        payload.append({
            "id": post["id"],
            "messages": messages,
            "meta": {
                "estimated_tokens": estimate_tokens(
                    title + body + post_body,
                    config["ai"].get("model_filter", "gpt-4o-mini")
                )
            }
        })
    return payload
