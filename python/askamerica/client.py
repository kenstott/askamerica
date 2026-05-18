import time
import uuid
from typing import Any, Optional

from .config import get_api_key
from .exceptions import AuthError, QueryError
from .quota import check_quota, report_usage


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

    quota = check_quota(key)
    query_id = str(uuid.uuid4())
    start_ms = time.time() * 1000

    try:
        conn = get_connection(key)
        rows = execute_query(conn, sql)
    except Exception as e:
        raise QueryError(str(e)) from e

    duration_ms = int(time.time() * 1000 - start_ms)

    if return_type == "records":
        actual_bytes = sum(
            sum(len(str(v)) for v in row.values()) for row in rows
        )
        result = rows
    else:
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "pandas is not installed. "
                "Run: pip install pandas  or use return_type='records'"
            )
        df = pd.DataFrame(rows)
        actual_bytes = int(df.memory_usage(deep=True).sum())
        result = df

    report_usage(
        query_id=query_id,
        table=_extract_table(sql),
        planned_bytes=actual_bytes,
        actual_bytes=actual_bytes,
        row_count=len(rows),
        duration_ms=duration_ms,
        query_text=sql,
        api_key=key,
    )

    _print_quota_reminder(quota, actual_bytes)
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
