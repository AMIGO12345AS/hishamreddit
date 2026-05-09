import os
import yaml

def get_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}
