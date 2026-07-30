"""End-to-end tests for fetch_aligned_series / resolve_geo through the DuckDB harness."""
import json

from askamerica import mcp_server


def test_fetch_aligned_corr_runs_in_engine(analytics_conn):
    resp = json.loads(mcp_server.fetch_aligned_series(
        series=[
            {"table": "econ.fred_indicators", "value": "value", "name": "unrate",
             "where": "series = 'UNRATE'", "time_col": '"date"'},
            {"table": "econ.treasury_yields", "value": "avg_interest_rate_amt",
             "name": "ten_yr", "where": "security_type_desc = 'Treasury Notes'",
             "time_col": "record_date"},
        ],
        on="month", stat="corr",
    ))
    assert "sql" in resp and "corr(" in resp["sql"]
    row = resp["rows"][0]
    assert row["n"] == 3                    # three aligned months
    assert -1.0 <= row["r"] <= 1.0          # a real correlation coefficient


def test_fetch_aligned_frame_returns_tidy_rows(analytics_conn):
    resp = json.loads(mcp_server.fetch_aligned_series(
        series=[
            {"table": "econ.fred_indicators", "value": "value", "name": "unrate",
             "where": "series = 'UNRATE'", "time_col": '"date"'},
            {"table": "econ.treasury_yields", "value": "avg_interest_rate_amt",
             "name": "ten_yr", "time_col": "record_date"},
        ],
        on="month",
    ))
    rows = resp["rows"]
    assert {"key", "unrate", "ten_yr"} <= set(rows[0].keys())
    assert len(rows) == 3


def test_fetch_aligned_bad_request_is_reported(analytics_conn):
    resp = json.loads(mcp_server.fetch_aligned_series(
        series=[{"table": "econ.fred_indicators", "value": "value", "time_col": '"date"'}],
        on="month", stat="corr",   # only one series -> validation error
    ))
    assert resp["error"] == "bad_request"


def test_resolve_state(analytics_conn):
    rows = json.loads(mcp_server.resolve_geo("California", level="state"))
    assert rows == [{"state_fips": "06", "state_abbr": "CA", "state_name": "California"}]


def test_resolve_state_by_abbr(analytics_conn):
    rows = json.loads(mcp_server.resolve_geo("tx", level="state"))
    assert rows[0]["state_fips"] == "48"


def test_resolve_county_within_state(analytics_conn):
    rows = json.loads(mcp_server.resolve_geo("Los Angeles", level="county",
                                             within_state="06"))
    assert rows[0]["county_fips"] == "06037"
