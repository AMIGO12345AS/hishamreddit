"""Thin wrapper around the OpenAI SDK for OpenAI-compatible providers.

Configuration (config.yaml / .env):
  ai.base_url     — provider endpoint, e.g. https://ai.megallm.io/v1
  ai.model_filter — model used in phase-1 filtering
  ai.model_deep   — model used in phase-2 deep analysis
  AI_API_KEY      — API key (.env)
  AI_BASE_URL     — optional base-URL override (.env)
"""
from openai import OpenAI
from config.config_loader import get_config
from utils.logger import setup_logger

log = setup_logger()
_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        cfg = get_config()["ai"]
        base_url = cfg.get("base_url", "")
        api_key  = cfg.get("api_key", "")

        if not api_key:
            raise RuntimeError(
                "AI_API_KEY is not set. Add it to your .env file."
            )
        if not base_url:
            raise RuntimeError(
                "ai.base_url is not configured. Set it in config/config.yaml "
                "or override with AI_BASE_URL in your .env file."
            )

        log.info(f"Connecting to AI provider: {base_url}")
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def chat_complete(messages: list, model: str, max_tokens: int = 1000) -> str:
    """Single blocking chat completion. Returns the response content string."""
    log.debug(f"chat_complete | model={model} | messages={len(messages)}")
    try:
        response = get_client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content.strip()
        log.debug(f"chat_complete | model={model} | response_len={len(content)}")
        return content
    except Exception as e:
        log.error(f"[AI ERROR] model={model} base_url={get_client().base_url} — {type(e).__name__}: {e}")
        raise
