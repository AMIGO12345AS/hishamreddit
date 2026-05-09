import json
from typing import Any

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_json(obj: Any, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def truncate(text: str, length: int) -> str:
    if not text:
        return ""
    return text if len(text) <= length else text[:length]
