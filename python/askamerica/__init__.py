from .client import query
from .auth import login
from .quota import get_quota, get_checkout
from .config import get_api_key
from .exceptions import AskAmericaError, AuthError, QuotaExceededError, QueryError

__version__ = "0.2.0"
__all__ = [
    "query",
    "login",
    "get_quota",
    "get_checkout",
    "get_api_key",
    "AskAmericaError",
    "AuthError",
    "QuotaExceededError",
    "QueryError",
]


def configure(api_key: str) -> None:
    from .config import save_config, load_config
    config = load_config()
    config["api_key"] = api_key
    save_config(config)
