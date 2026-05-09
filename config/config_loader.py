import yaml
import os
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = "config/config.yaml"
PROMPT_PATH = "gpt/prompts"

# Prompt template constants
PROMPT_FILTER = "filter"
PROMPT_INSIGHT = "insight"
PROMPT_COMMUNITY_DISCOVERY = "community_discovery"
PROMPT_COMMUNITY_DISCOVERY_SYSTEM = "community_discovery_system"
PROMPTS_ALL = [
    PROMPT_FILTER, PROMPT_INSIGHT, PROMPT_COMMUNITY_DISCOVERY, PROMPT_COMMUNITY_DISCOVERY_SYSTEM
]


def get_config():
    with open(CONFIG_PATH, "r") as f:
        raw_config = yaml.safe_load(f)

    # Inject Reddit credentials from .env
    raw_config["reddit"] = {
        "client_id":     os.getenv("REDDIT_CLIENT_ID"),
        "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
        "user_agent":    os.getenv("REDDIT_USER_AGENT"),
        "username":      os.getenv("REDDIT_USERNAME"),
        "password":      os.getenv("REDDIT_PASSWORD"),
    }

    # Inject AI credentials from .env
    # AI_API_KEY  — API key for the configured provider
    # AI_BASE_URL — optional override; falls back to config.yaml value
    raw_config["ai"]["api_key"] = os.getenv("AI_API_KEY")
    env_base_url = os.getenv("AI_BASE_URL")
    if env_base_url:
        raw_config["ai"]["base_url"] = env_base_url

    # Inject prompts from files
    raw_config["prompts"] = load_all_prompts()

    return raw_config


def load_all_prompts() -> dict:
    """Load all prompt templates from the prompts directory."""
    prompts = {}
    for key in PROMPTS_ALL:
        path = os.path.join(PROMPT_PATH, f"{key}.txt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                prompts[key] = f.read().strip()
        except Exception as e:
            raise Exception(f"Error loading prompt '{key}' from {path}: {e}") from None
    return prompts
