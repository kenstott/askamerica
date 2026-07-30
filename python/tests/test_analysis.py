"""Unit tests for the SQL builders (pure, no database)."""
import pytest

from askamerica.analysis import build_aligned_sql, build_resolve_sql


# ── build_aligned_sql: shape ─────────────────────────────────────────────────

def test_corr_pushes_stat_into_sql():
    sql = build_aligned_sql(
        [
            {"table": "econ.fred_indicators", "value": "value", "name": "unrate",
             "where": "series = 'UNRATE'", "time_col": '"date"'},
            {"table": "econ.treasury_yields", "value": "avg_interest_rate_amt",
             "name": "ten_yr", "time_col": "record_date"},
        ],
        on="month", stat="corr",
    )
    assert "corr(unrate, ten_yr)" in sql
    assert "regr_count(unrate, ten_yr) AS n" in sql
    assert "date_trunc('month'" in sql
    assert "FULL OUTER JOIN" in sql
    assert "FETCH FIRST" not in sql  # stat returns a scalar, no row cap


def test_regr_models_second_on_first():
    sql = build_aligned_sql(
        [
            {"table": "census.acs_population", "value": "total_population",
             "name": "pop", "geo_col": "state"},
            {"table": "econ.state_wages", "value": "avg_weekly_wage",
             "name": "wage", "geo_col": "state_fips"},
        ],
        on="state", stat="regr",
    )
    assert "regr_slope(wage, pop)" in sql      # y=wage ~ x=pop
    assert "regr_r2(wage, pop) AS r2" in sql


def test_time_convention_normalizers():
    # BLS year+period, BEA quarter, and annual-only each map to a date_trunc.
    bls = build_aligned_sql([{"table": "econ.inflation_metrics", "value": "value",
                              "year_col": "year", "period_col": "period"}], on="month")
    assert "make_date(year, CAST(substr(period, 2) AS INTEGER), 1)" in bls
    bea = build_aligned_sql([{"table": "econ.gdp", "value": "v",
                              "quarter_col": "time_period"}], on="quarter")
    assert "substr(time_period, 1, 4)" in bea
    ann = build_aligned_sql([{"table": "census.acs", "value": "v",
                              "year_only_col": "year"}], on="year")
    assert "make_date(year, 1, 1)" in ann


def test_frame_without_stat_has_row_cap_and_order():
    sql = build_aligned_sql(
        [
            {"table": "a.t", "value": "v", "name": "x", "time_col": "d"},
            {"table": "b.t", "value": "v", "name": "y", "time_col": "d"},
        ],
        on="month", limit=100,
    )
    assert "ORDER BY key" in sql
    assert "FETCH FIRST 100 ROWS ONLY" in sql


# ── build_aligned_sql: validation ────────────────────────────────────────────

def test_stat_requires_two_series():
    with pytest.raises(ValueError, match="at least two series"):
        build_aligned_sql([{"table": "a.t", "value": "v", "time_col": "d"}],
                          on="month", stat="corr")


def test_bad_on_rejected():
    with pytest.raises(ValueError, match="on must be one of"):
        build_aligned_sql([{"table": "a.t", "value": "v", "time_col": "d"}], on="fortnight")


def test_missing_key_column_rejected():
    with pytest.raises(ValueError, match="time_col"):
        build_aligned_sql([{"table": "a.t", "value": "v"}], on="month")


def test_name_alias_cannot_inject():
    with pytest.raises(ValueError, match="simple identifier"):
        build_aligned_sql(
            [{"table": "a.t", "value": "v", "time_col": "d",
              "name": "x; DROP TABLE y"}],
            on="month",
        )


def test_unknown_agg_rejected():
    with pytest.raises(ValueError, match="agg"):
        build_aligned_sql(
            [{"table": "a.t", "value": "v", "time_col": "d", "agg": "sneaky()"}],
            on="month",
        )


# ── build_resolve_sql ────────────────────────────────────────────────────────

def test_resolve_state_matches_name_abbr_or_fips():
    sql = build_resolve_sql("California", level="state")
    assert "geo.state_ref" in sql
    assert "lower(state_name) LIKE '%california%'" in sql
    assert "lower(state_abbr) = lower('California')" in sql
    assert "state_fips = 'California'" in sql


def test_resolve_county_scoped_to_state():
    sql = build_resolve_sql("Washington", level="county", within_state="06")
    assert "geo.counties" in sql
    assert "state_fips = '06'" in sql


def test_resolve_escapes_quotes():
    sql = build_resolve_sql("Prince George's", level="county")
    assert "prince george''s" in sql  # doubled quote, not a broken literal


def test_resolve_bad_level():
    with pytest.raises(ValueError, match="level must be"):
        build_resolve_sql("x", level="planet")
