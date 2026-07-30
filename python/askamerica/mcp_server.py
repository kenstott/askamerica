#!/usr/bin/env python3
"""
AskAmerica MCP server — exposes US government JDBC data as Claude Desktop tools.

Install
-------
pip install 'askamerica[mcp]'
askamerica install-engine

Configure Claude Desktop
------------------------
Add to ~/Library/Application Support/Claude/claude_desktop_config.json:

{
  "mcpServers": {
    "askamerica": {
      "command": "python",
      "args": ["-m", "askamerica.mcp_server"],
      "env": {
        "ASKAMERICA_API_KEY": "aa_free_..."
      }
    }
  }
}
"""
import json
import os
import sys
from typing import Optional

from .config import get_api_key, _is_selftest_session
from .exceptions import AuthError, EngineNotInstalledError, QuotaExceededError
from .engine import execute_query, get_connection, get_metadata
from .quota import check_quota
from .analysis import build_aligned_sql, build_resolve_sql

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "mcp package not installed. Run: pip install 'askamerica[mcp]'",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP(
    "AskAmerica",
    instructions=(
        "Query US government data using SQL. "
        "Schemas: sec (SEC filings/XBRL), geo (TIGER/FIPS boundaries), "
        "econ (BLS/BEA indicators), census (ACS/decennial), crime (FBI UCR), "
        "weather (NOAA GHCND), ref (NAICS/SIC/state lookup), fec (campaign finance), "
        "fedregister (federal rules/notices), cyber_vuln (NVD CVEs), "
        "cyber_threat (CISA KEV), energy (EIA), health (CDC/CMS/trials), "
        "edu (NCES IPEDS), econ_reference (BLS area/industry codes). "
        "Always call list_tables(schema) before querying. "
        "Use FETCH FIRST N ROWS ONLY to limit large results. "
        "Join across schemas using geo.states / geo.counties for FIPS joins. "
        "\n\n"
        "STATISTICAL ANALYSIS RUNS IN SQL — push the computation into the query "
        "instead of pulling rows to compute by hand; the engine evaluates these "
        "aggregates natively and returns just the result. Available functions: "
        "correlation — corr(y,x), covar_pop, covar_samp; "
        "linear regression — regr_slope(y,x), regr_intercept(y,x), regr_r2(y,x), "
        "regr_count, regr_avgx, regr_avgy, regr_sxx, regr_syy, regr_sxy; "
        "distribution — median(x), quantile_cont(x,p), quantile_disc(x,p), mode(x), "
        "stddev_samp, stddev_pop, var_samp, var_pop; "
        "shape — skewness(x), kurtosis(x), mad(x); "
        "and window functions lag()/lead() for lagged and cross-correlation analysis. "
        "Always select COUNT(*) AS n alongside a corr/regr so significance can be "
        "judged, and remember correlation is not causation. "
        "To relate series across datasets, first ALIGN them on a common key — a "
        "date/period truncated to a shared grain, or a FIPS geography — then correlate; "
        "the fetch_aligned_series tool does this alignment and can return corr/regr "
        "computed in the engine. Resolve place names to FIPS codes with resolve_geo "
        "before joining a user-named place to census/econ/geo tables."
    ),
)

_api_key: Optional[str] = None


def _selftest_bypass(key: str) -> bool:
    """True when the self-test / warm-up bypass is active, mirroring the engine's
    UsageMetering.selfTestBypassEnabled(): the operator opts in via
    ASKAMERICA_SELFTEST_ENABLED=true (env), and the engine's isSelfTestSession()
    remains the real token validator on the Java side. Also honors the hashed
    warm-up session token directly."""
    if _is_selftest_session(key):
        return True
    return os.environ.get("ASKAMERICA_SELFTEST_ENABLED", "").strip().lower() == "true"


def _key() -> str:
    global _api_key
    if _api_key is None:
        _api_key = get_api_key()
    if not _api_key:
        raise AuthError(
            "ASKAMERICA_API_KEY is not set. "
            "Add it to your Claude Desktop MCP env config."
        )
    return _api_key


@mcp.tool()
def list_schemas() -> str:
    """List all available US government data schemas."""
    conn = get_connection(_key())
    meta = get_metadata(conn)
    rs = meta.getSchemas()
    schemas = []
    while rs.next():
        schemas.append(str(rs.getString("TABLE_SCHEM")))
    rs.close()
    return json.dumps(sorted(schemas))


@mcp.tool()
def list_tables(schema: str) -> str:
    """
    List tables and views in a schema.

    Parameters
    ----------
    schema : str
        Schema name (e.g. 'sec', 'geo', 'census'). Case-insensitive.
    """
    conn = get_connection(_key())
    meta = get_metadata(conn)
    rs = meta.getTables(None, schema.lower(), "%", None)
    tables = []
    while rs.next():
        tables.append({
            "table": str(rs.getString("TABLE_NAME")),
            "type": str(rs.getString("TABLE_TYPE")),
        })
    rs.close()
    return json.dumps(tables)


@mcp.tool()
def describe_table(schema: str, table: str) -> str:
    """
    Get column names, types, and nullability for a table.

    Parameters
    ----------
    schema : str
        Schema name (e.g. 'sec').
    table : str
        Table name (e.g. 'filing_metadata').
    """
    conn = get_connection(_key())
    meta = get_metadata(conn)
    rs = meta.getColumns(None, schema.lower(), table.lower(), "%")
    columns = []
    while rs.next():
        columns.append({
            "name": str(rs.getString("COLUMN_NAME")),
            "type": str(rs.getString("TYPE_NAME")),
            "nullable": rs.getInt("NULLABLE") == 1,
        })
    rs.close()
    return json.dumps(columns)


@mcp.tool()
def query(sql: str, limit: int = 500) -> str:
    """
    Execute a SQL query against US government data.

    Automatically appends FETCH FIRST {limit} ROWS ONLY if no row limit is present.
    Returns a JSON array of row objects.

    Statistical analysis runs IN the engine — push it into the SQL rather than
    pulling rows to compute by hand. These aggregates are available:
      correlation : corr(y,x), covar_pop, covar_samp
      regression  : regr_slope(y,x), regr_intercept(y,x), regr_r2(y,x),
                    regr_count, regr_avgx, regr_avgy, regr_sxx, regr_syy, regr_sxy
      distribution: median(x), quantile_cont(x,p), quantile_disc(x,p), mode(x),
                    stddev_samp, stddev_pop, var_samp, var_pop
      shape       : skewness(x), kurtosis(x), mad(x)
      windows     : lag(), lead()  (for lagged / cross-correlation analysis)
    Always select COUNT(*) AS n alongside a corr/regr so significance can be
    judged; correlation is not causation. To relate series ACROSS datasets, first
    align them on a common key (a date/period truncated to a shared grain, or a
    FIPS geography), then correlate.

    Parameters
    ----------
    sql   : Calcite SQL — reference tables as schema.table (e.g. sec.filing_metadata)
    limit : Maximum rows to return (default 500, max 5000)

    Examples
    --------
    SELECT cik, company_name, filing_type, filing_date
    FROM sec.filing_metadata
    ORDER BY filing_date DESC
    FETCH FIRST 10 ROWS ONLY

    SELECT state_abbr, SUM(count) AS total_offenses
    FROM crime.offenses_by_state
    WHERE year = 2022
    GROUP BY state_abbr
    ORDER BY total_offenses DESC
    FETCH FIRST 10 ROWS ONLY

    -- statistics computed in-engine (push analysis into SQL):
    SELECT corr(male_population, female_population)       AS r,
           regr_slope(female_population, male_population) AS slope,
           regr_r2(female_population, male_population)    AS r2,
           median(total_population)                       AS median_pop,
           COUNT(*)                                       AS n
    FROM census.acs_population
    WHERE year = 2020
    """
    # Quota gate: if the user is out of quota, prompt to upgrade instead of running.
    # Self-test / warm-up sessions carry the fixed bypass token and skip the gate
    # entirely (mirrors client.query); the engine applies the matching bypass when
    # -Daskamerica.selftest.enabled=true is set.
    if not _selftest_bypass(_key()):
        try:
            check_quota(_key())
        except QuotaExceededError as e:
            return json.dumps({
                "error": "quota_exceeded",
                "message": str(e),
                "upgrade_url": e.upgrade_url,
            })
        except AuthError as e:
            return json.dumps({"error": "unauthorized", "message": str(e)})

    effective_limit = min(max(1, limit), 5000)
    lower = sql.lower()
    if "fetch first" not in lower and "limit" not in lower:
        sql = f"{sql.rstrip(';')} FETCH FIRST {effective_limit} ROWS ONLY"

    conn = get_connection(_key())
    rows = execute_query(conn, sql)
    return json.dumps(rows, default=str)


def _quota_or_error() -> Optional[str]:
    """Shared quota/auth gate. Returns a JSON error string, or None to proceed."""
    if _selftest_bypass(_key()):
        return None  # self-test / warm-up bypass (see query())
    try:
        check_quota(_key())
        return None
    except QuotaExceededError as e:
        return json.dumps({
            "error": "quota_exceeded",
            "message": str(e),
            "upgrade_url": e.upgrade_url,
        })
    except AuthError as e:
        return json.dumps({"error": "unauthorized", "message": str(e)})


@mcp.tool()
def fetch_aligned_series(series: list, on: str = "month",
                         stat: Optional[str] = None, limit: int = 500) -> str:
    """
    Align multiple US-government series onto a common key and return them tidy,
    or (with `stat`) the statistic computed in the engine over the first two.

    This is the tool to reach for whenever a question spans two or more datasets
    that must be lined up before comparing — the align/resample/join is generated
    as one DuckDB statement, normalizing the differing govdata time conventions.
    For a single-table stat you can just call `query` with DuckDB's corr/regr_*/
    stddev_samp/quantile_cont directly.

    Parameters
    ----------
    series : list of spec dicts. Each spec:
        table : "schema.table"                          (required)
        value : column or SQL expression to aggregate    (required)
        name  : output column name (identifier)          (optional; s0,s1,...)
        agg   : downsample aggregate                      (default "avg")
        where : SQL filter, e.g. "series = 'UNRATE'"      (optional)
        # exactly one key source, matching `on`:
        time_col              : a DATE column (FRED, treasury)
        year_col + period_col : BLS year + "M01".."M12"
        quarter_col           : BEA "2023Q1"
        year_only_col         : annual-partition tables
        geo_col               : FIPS column, when on is state/county/geo
    on   : "day" | "month" | "quarter" | "year" (time), or "state" | "county"
           | "geo" (join on a FIPS column). Default "month".
    stat : None -> aligned rows; "corr" -> {r, n}; "regr" -> {slope, intercept,
           r2, n} modeling series[1] ~ series[0]. Needs >= 2 series.
    limit: row cap when returning aligned rows (ignored when `stat` is set).

    Returns a JSON object {"sql": <generated SQL>, "rows": [...]} — the SQL is
    included so the result is auditable and easy to refine with `query`.

    Examples
    --------
    # National monthly: unemployment vs 10-yr treasury yield, then correlate
    fetch_aligned_series([
        {"table": "econ.fred_indicators", "value": "value", "name": "unrate",
         "where": "series = 'UNRATE'", "time_col": "\\"date\\""},
        {"table": "econ.treasury_yields", "value": "avg_interest_rate_amt",
         "name": "ten_yr", "where": "security_type_desc = 'Treasury Notes'",
         "time_col": "record_date"},
    ], on="month", stat="corr")

    # State panel (join on FIPS): 2020 population vs same-year avg weekly wage
    fetch_aligned_series([
        {"table": "census.acs_population", "value": "total_population",
         "name": "pop", "where": "year = 2020", "geo_col": "state"},
        {"table": "econ.state_wages", "value": "avg_weekly_wage",
         "name": "wage", "where": "year = 2020", "geo_col": "state_fips"},
    ], on="state", stat="regr")
    """
    gate = _quota_or_error()
    if gate is not None:
        return gate
    try:
        sql = build_aligned_sql(series, on=on, stat=stat,
                                limit=None if stat else limit)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": "bad_request", "message": str(e)})

    conn = get_connection(_key())
    rows = execute_query(conn, sql)
    return json.dumps({"sql": sql, "rows": rows}, default=str)


@mcp.tool()
def resolve_geo(term: str, level: str = "state",
                within_state: Optional[str] = None) -> str:
    """
    Resolve a free-text place name to canonical FIPS identifiers, so downstream
    joins key on the right code instead of a guessed one.

    Call this before joining a place the user named in words (e.g. "California",
    "Los Angeles County") to geo/census/econ tables. Returns candidate rows —
    more than one when the term is ambiguous (e.g. a county name shared across
    states); pass `within_state` (a 2-digit state FIPS) to disambiguate.

    Parameters
    ----------
    term  : place text or code — a name ("California"), abbr ("CA"), 2-digit
            state FIPS ("06"), 5-digit county FIPS ("06037"), or ZCTA ("90012").
    level : "state" -> geo.state_ref (state_fips, state_abbr, state_name);
            "county" -> geo.counties (county_fips, state_fips, county_name);
            "zcta" -> geo.zcta_ref (zcta, latitude, longitude). Default "state".
    within_state : optional 2-digit state FIPS to scope a county lookup.
    """
    gate = _quota_or_error()
    if gate is not None:
        return gate
    try:
        sql = build_resolve_sql(term, level=level, within_state=within_state)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": "bad_request", "message": str(e)})

    conn = get_connection(_key())
    rows = execute_query(conn, sql)
    return json.dumps(rows, default=str)


if __name__ == "__main__":
    mcp.run()
