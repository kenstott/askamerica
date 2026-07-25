from .client import query
from .auth import login
from .quota import get_quota, get_checkout
from .config import get_api_key
from .exceptions import AskAmericaError, AuthError, QuotaExceededError, QueryError

__version__ = "0.45.0"
__all__ = [
    "query",
    "connect",
    "login",
    "get_quota",
    "get_checkout",
    "get_api_key",
    "AskAmericaError",
    "AuthError",
    "QuotaExceededError",
    "QueryError",
]


def connect(api_key: str = None):
    """
    Return a raw JDBC connection for use with the standard DBAPI cursor pattern.
    JPype is managed internally — callers never import it directly.

    Example
    -------
    import askamerica as aa
    conn = aa.connect()
    stmt = conn.createStatement()
    rs   = stmt.executeQuery("SELECT company_name FROM sec.filing_metadata FETCH FIRST 5 ROWS ONLY")
    while rs.next():
        print(rs.getString("company_name"))
    conn.close()
    """
    from .engine import get_connection
    from .config import get_api_key as _get_api_key
    key = api_key or _get_api_key()
    if not key:
        raise AuthError("No API key configured. Run: askamerica login")
    return get_connection(key)


def configure(api_key: str) -> None:
    from .config import save_config, load_config
    config = load_config()
    config["api_key"] = api_key
    save_config(config)
