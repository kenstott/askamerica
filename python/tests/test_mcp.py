"""Integration tests for the MCP server: the tools retrieve data and enforce quota.

The engine's JDBC connection is replaced with a small JDBC-shaped wrapper over an
in-memory DuckDB, so we exercise the real mcp_server tool logic (SQL execution,
row limiting, JSON serialization, quota gate) without the packaged engine JAR.
"""
import json

import pytest

# Skip cleanly if the MCP SDK / DuckDB aren't installed (pip install 'askamerica[mcp]' duckdb).
pytest.importorskip("mcp.server.fastmcp")
duckdb = pytest.importorskip("duckdb")

from askamerica import mcp_server  # noqa: E402
from askamerica.exceptions import QuotaExceededError  # noqa: E402


# ── a minimal JDBC-shaped wrapper over DuckDB ────────────────────────────────
class _Meta:
    def __init__(self, cols):
        self._cols = cols

    def getColumnCount(self):
        return len(self._cols)

    def getColumnName(self, i):  # 1-based
        return self._cols[i - 1]


class _ResultSet:
    def __init__(self, cols, rows):
        self._cols, self._rows, self._i, self._null = cols, rows, -1, False

    def getMetaData(self):
        return _Meta(self._cols)

    def next(self):
        self._i += 1
        return self._i < len(self._rows)

    def getObject(self, i):  # 1-based
        v = self._rows[self._i][i - 1]
        self._null = v is None
        return v

    def wasNull(self):
        return self._null

    def close(self):
        pass


class _Statement:
    def __init__(self, con):
        self._con = con

    def executeQuery(self, sql):
        res = self._con.execute(sql)
        cols = [d[0] for d in res.description]
        return _ResultSet(cols, res.fetchall())

    def close(self):
        pass


class _Connection:
    def __init__(self, con):
        self._con = con

    def createStatement(self):
        return _Statement(self._con)


@pytest.fixture
def fake_conn(monkeypatch):
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE sec_filings AS "
        "SELECT * FROM (VALUES (1,'Acme'),(2,'Beta'),(3,'Gamma')) t(cik, name)"
    )
    conn = _Connection(con)
    monkeypatch.setenv("ASKAMERICA_API_KEY", "aa_test_key")
    monkeypatch.setattr(mcp_server, "_api_key", None)
    monkeypatch.setattr(mcp_server, "get_connection", lambda key: conn)
    return conn


def test_query_retrieves_data(fake_conn, monkeypatch):
    monkeypatch.setattr(mcp_server, "check_quota", lambda key: {"remaining_bytes": 10 ** 12})
    rows = json.loads(mcp_server.query("SELECT cik, name FROM sec_filings ORDER BY cik"))
    assert len(rows) == 3
    assert rows[0] == {"cik": 1, "name": "Acme"}
    assert {r["name"] for r in rows} == {"Acme", "Beta", "Gamma"}


def test_query_appends_row_limit(fake_conn, monkeypatch):
    captured = {}
    real = mcp_server.execute_query
    monkeypatch.setattr(mcp_server, "check_quota", lambda key: {})
    monkeypatch.setattr(mcp_server, "execute_query",
                        lambda conn, sql: (captured.__setitem__("sql", sql), real(conn, sql))[1])
    mcp_server.query("SELECT * FROM sec_filings", limit=2)
    assert "FETCH FIRST 2 ROWS ONLY" in captured["sql"]


def test_query_blocks_when_over_quota(fake_conn, monkeypatch):
    def over(key):
        raise QuotaExceededError(remaining_bytes=0, period="2026-07",
                                 upgrade_url="https://askamerica.ai/upgrade")
    monkeypatch.setattr(mcp_server, "check_quota", over)
    resp = json.loads(mcp_server.query("SELECT * FROM sec_filings"))
    assert resp["error"] == "quota_exceeded"
    assert "/upgrade" in resp["upgrade_url"]
