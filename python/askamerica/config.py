import os
import json
from pathlib import Path
from typing import Optional

API_BASE_URL = "https://api.askamerica.ai"
CONFIG_PATH = Path.home() / ".askamerica" / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_api_key() -> Optional[str]:
    return os.environ.get("ASKAMERICA_API_KEY") or load_config().get("api_key")
