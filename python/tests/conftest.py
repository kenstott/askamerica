"""Shared test harness: a JDBC-shaped wrapper over in-memory DuckDB.

Lets the real mcp_server tool logic (SQL build + execute + JSON) run without the
packaged engine JAR. Mirrors the local harness in test_mcp.py, but seeds the
schemas/tables the analytical tools query (econ.*, geo.*) so fetch_aligned_series
and resolve_geo can be exercised end-to-end.
"""
import pytest

pytest.importorskip("mcp.server.fastmcp")
duckdb = pytest.importorskip("duckdb")


# ── minimal JDBC-shaped wrapper over DuckDB ──────────────────────────────────
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
def analytics_conn(monkeypatch):
    """DuckDB seeded with the econ/geo tables the analytical tools target."""
    from askamerica import mcp_server

    con = duckdb.connect()
    con.execute("CREATE SCHEMA econ; CREATE SCHEMA geo;")

    # National monthly-ish series: FRED (monthly dates) + treasury (daily).
    con.execute("""
        CREATE TABLE econ.fred_indicators AS SELECT * FROM (VALUES
            ('UNRATE', DATE '2020-01-01', 3.6),
            ('UNRATE', DATE '2020-02-01', 3.5),
            ('UNRATE', DATE '2020-03-01', 4.4)
        ) t(series, "date", value)
    """)
    con.execute("""
        CREATE TABLE econ.treasury_yields AS SELECT * FROM (VALUES
            ('Treasury Notes', DATE '2020-01-10', 1.80),
            ('Treasury Notes', DATE '2020-01-24', 1.60),
            ('Treasury Notes', DATE '2020-02-14', 1.55),
            ('Treasury Notes', DATE '2020-03-13', 0.90)
        ) t(security_type_desc, record_date, avg_interest_rate_amt)
    """)
    con.execute("""
        CREATE TABLE geo.state_ref AS SELECT * FROM (VALUES
            ('06', 'CA', 'California'),
            ('36', 'NY', 'New York'),
            ('48', 'TX', 'Texas')
        ) t(state_fips, state_abbr, state_name)
    """)
    con.execute("""
        CREATE TABLE geo.counties AS SELECT * FROM (VALUES
            ('06037', '06', 'Los Angeles County'),
            ('36061', '36', 'New York County'),
            ('48201', '48', 'Harris County')
        ) t(county_fips, state_fips, county_name)
    """)

    conn = _Connection(con)
    monkeypatch.setenv("ASKAMERICA_API_KEY", "aa_test_key")
    monkeypatch.setattr(mcp_server, "_api_key", None)
    monkeypatch.setattr(mcp_server, "get_connection", lambda key: conn)
    monkeypatch.setattr(mcp_server, "check_quota", lambda key: {"remaining_bytes": 10 ** 12})
    return con
