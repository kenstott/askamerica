from typing import Any, Optional

from .config import get_api_key, _is_selftest_session
from .exceptions import AuthError, QueryError
from .quota import check_quota, estimate_egress_bytes


def query(
    sql: str,
    api_key: Optional[str] = None,
    return_type: str = "df",
) -> Any:
    """
    Execute a SQL query against US government data via the govdata JDBC engine.

    Requires the askamerica-engine JAR. Install it with: askamerica install-engine

    Parameters
    ----------
    sql:         Calcite SQL (schemas: sec, geo, econ, census, crime, weather, ...)
    api_key:     API key (default: ASKAMERICA_API_KEY env var or ~/.askamerica/config.json)
    return_type: 'df' for pandas DataFrame (default), 'records' for list of dicts

    Example
    -------
    import askamerica as aa
    df = aa.query("SELECT cik, company_name FROM sec.filing_metadata FETCH FIRST 5 ROWS ONLY")
    """
    from .engine import get_connection, execute_query

    key = api_key or get_api_key()
    if not key:
        raise AuthError("No API key configured. Run: askamerica login")

    # Pre-flight quota gate (fail fast). Usage itself is metered in the engine
    # (AskAmerica JDBC driver), so every access path — JDBC, Python, MCP — reports
    # uniformly and we must NOT double-count here. Internal self-test / warm-up
    # sessions are synthetic and skip the gate.
    quota = None if _is_selftest_session(key) else check_quota(key)

    try:
        conn = get_connection(key)
        rows = execute_query(conn, sql)
    except Exception as e:
        raise QueryError(str(e)) from e

    if return_type == "records":
        result = rows
    else:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas is not installed. "
                "Run: pip install pandas  or use return_type='records'"
            )
        result = pd.DataFrame(rows)

    if quota is not None:
        _print_quota_reminder(quota, estimate_egress_bytes(rows))
    return result


def _extract_table(sql: str) -> str:
    import re
    match = re.search(r'\bFROM\s+([\w.]+)', sql, re.IGNORECASE)
    return match.group(1) if match else "unknown"


def _print_quota_reminder(quota: dict, used_bytes: int) -> None:
    remaining = quota["remaining_bytes"] - used_bytes
    limit = quota["limit_bytes"]
    pct_used = ((limit - remaining) / limit) * 100
    remaining_gb = remaining / (1024 ** 3)
    if pct_used >= 80:
        print(
            f"[askamerica] {pct_used:.0f}% of monthly quota used. "
            f"{remaining_gb:.2f} GB remaining. "
            f"Upgrade at https://askamerica.ai/upgrade"
        )
