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
import sys
from typing import Optional

from .config import get_api_key
from .exceptions import AuthError, EngineNotInstalledError, QuotaExceededError
from .engine import execute_query, get_connection, get_metadata
from .quota import check_quota

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
        "Join across schemas using geo.states / geo.counties for FIPS joins."
    ),
)

_api_key: Optional[str] = None


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
    """
    # Quota gate: if the user is out of quota, prompt to upgrade instead of running.
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


if __name__ == "__main__":
    mcp.run()
