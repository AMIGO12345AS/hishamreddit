"""Thin wrapper around the OpenAI SDK for OpenAI-compatible providers.

Configuration (config.yaml / .env):
  ai.base_url     — provider endpoint, e.g. https://api.frenix.sh/v1
  ai.model_filter — model used in phase-1 filtering
  ai.model_deep   — model used in phase-2 deep analysis
  AI_API_KEY      — API key (.env)
  AI_BASE_URL     — optional base-URL override (.env)
"""
from openai import OpenAI
from config.config_loader import get_config

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        cfg = get_config()["ai"]
        _client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
        )
    return _client


def chat_complete(messages: list, model: str, max_tokens: int = 1000) -> str:
    """Single blocking chat completion. Returns the response content string."""
    response = get_client().chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()
