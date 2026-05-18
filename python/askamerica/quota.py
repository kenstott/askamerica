import time
import requests
from typing import Optional
from .config import API_BASE_URL, get_api_key
from .exceptions import AuthError, QuotaExceededError

_cache: dict = {}
_cache_ttl = 300  # 5 minutes


def get_quota(api_key: Optional[str] = None) -> dict:
    key = api_key or get_api_key()
    if not key:
        raise AuthError("No API key. Run: askamerica login")

    now = time.time()
    if _cache.get("expires_at", 0) > now:
        return _cache["data"]

    r = requests.get(f"{API_BASE_URL}/v1/quota", headers={"X-API-Key": key})
    if r.status_code == 401:
        raise AuthError("Invalid API key. Run: askamerica login")
    r.raise_for_status()

    data = r.json()
    _cache["data"] = data
    _cache["expires_at"] = now + _cache_ttl
    return data


def check_quota(api_key: Optional[str] = None) -> dict:
    quota = get_quota(api_key)
    if quota["remaining_bytes"] <= 0:
        raise QuotaExceededError(
            remaining_bytes=quota["remaining_bytes"],
            period=quota["period"],
            upgrade_url=quota.get("upgrade_url"),
        )
    return quota


def get_checkout(api_key: Optional[str] = None) -> dict:
    key = api_key or get_api_key()
    if not key:
        raise AuthError("No API key. Run: askamerica login")
    r = requests.get(f"{API_BASE_URL}/v1/checkout", headers={"X-API-Key": key})
    if r.status_code == 401:
        raise AuthError("Invalid API key.")
    r.raise_for_status()
    return r.json()


def report_usage(
    query_id: str,
    table: str,
    planned_bytes: int,
    actual_bytes: int,
    row_count: int,
    duration_ms: int,
    query_text: str,
    api_key: Optional[str] = None,
) -> None:
    key = api_key or get_api_key()
    if not key:
        return
    try:
        requests.post(
            f"{API_BASE_URL}/v1/metering/usage",
            headers={"X-API-Key": key},
            json={
                "query_id": query_id,
                "table": table,
                "planned_bytes": planned_bytes,
                "actual_bytes": actual_bytes,
                "row_count": row_count,
                "duration_ms": duration_ms,
                "query_text": query_text,
            },
            timeout=5,
        )
        # invalidate quota cache after reporting
        _cache.clear()
    except Exception:
        pass  # metering is best-effort, never block the user
