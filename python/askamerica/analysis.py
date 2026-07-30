"""
SQL builders for the AskAmerica analytical tools.

Pure string-building + validation, deliberately DB-free so it unit-tests without
the engine JAR. The generated SQL runs in the client-side DuckDB engine (the JVM
the Python process spawns), reading Parquet from R2. Nothing here talks to the
database; mcp_server.py wires these into @mcp.tool() wrappers that add the quota
gate and execute.

Two capabilities:
  * build_aligned_sql  -- align N government series onto a common key (a time
    grain or a FIPS geography), normalizing the mismatched govdata time
    conventions (FRED date / BLS year+"M01" / BEA "2023Q1" / annual year), and
    optionally computing a statistic (corr, regr) over the first two series in
    the DuckDB engine instead of in the model's context.
  * build_resolve_sql  -- resolve free-text place terms to canonical FIPS codes
    via geo.state_ref / geo.counties / geo.zcta_ref, so cross-schema joins key
    on the right identifier instead of a guessed one.
"""
from typing import Optional

# ── shared helpers ───────────────────────────────────────────────────────────

_TIME_GRAINS = ("day", "month", "quarter", "year")
_GEO_LEVELS = ("state", "county", "geo")
_STATS = ("corr", "regr")
_IDENT_MAXLEN = 63


def _sql_str(value: str) -> str:
    """Single-quote and escape a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _check_ident(name: str, what: str) -> str:
    """Guard an output column alias: identifier-ish, so it can't inject SQL."""
    if not name or len(name) > _IDENT_MAXLEN or not all(
        c.isalnum() or c == "_" for c in name
    ):
        raise ValueError(
            f"{what} must be a simple identifier (letters/digits/underscore, "
            f"<= {_IDENT_MAXLEN} chars); got {name!r}"
        )
    return name


# ── fetch_aligned_series ─────────────────────────────────────────────────────

def _key_expr(spec: dict, on: str) -> str:
    """SQL expression normalizing a series' key column(s) to the target `on`."""
    if on in _TIME_GRAINS:
        grain = on
        if "time_col" in spec:                              # FRED / treasury: DATE
            return f"date_trunc('{grain}', {spec['time_col']})"
        if "year_col" in spec and "period_col" in spec:     # BLS: year + "M01".."M12"
            y, p = spec["year_col"], spec["period_col"]
            return (f"date_trunc('{grain}', "
                    f"make_date({y}, CAST(substr({p}, 2) AS INTEGER), 1))")
        if "quarter_col" in spec:                           # BEA: "2023Q1"
            q = spec["quarter_col"]
            return (f"date_trunc('{grain}', make_date("
                    f"CAST(substr({q}, 1, 4) AS INTEGER), "
                    f"(CAST(substr({q}, 6, 1) AS INTEGER) - 1) * 3 + 1, 1))")
        if "year_only_col" in spec:                         # annual partition tables
            return f"date_trunc('{grain}', make_date({spec['year_only_col']}, 1, 1))"
        raise ValueError(
            f"series {spec.get('name')!r}: for on={on!r} give one of "
            "time_col | (year_col & period_col) | quarter_col | year_only_col"
        )
    if on in _GEO_LEVELS:
        if "geo_col" not in spec:
            raise ValueError(
                f"series {spec.get('name')!r}: for on={on!r} give geo_col "
                "(the FIPS column to join on)"
            )
        return spec["geo_col"]
    raise ValueError(f"on must be one of {_TIME_GRAINS + _GEO_LEVELS}; got {on!r}")


def build_aligned_sql(series: list, on: str = "month",
                      stat: Optional[str] = None,
                      limit: Optional[int] = 500) -> str:
    """Generate the single DuckDB statement that aligns the series (see module doc)."""
    if not isinstance(series, list) or len(series) < 1:
        raise ValueError("series must be a non-empty list of spec dicts")
    if stat is not None and stat not in _STATS:
        raise ValueError(f"stat must be one of {_STATS} or None; got {stat!r}")
    if stat is not None and len(series) < 2:
        raise ValueError(f"stat={stat!r} needs at least two series")

    ctes, cols = [], []
    for i, spec in enumerate(series):
        if not isinstance(spec, dict) or "table" not in spec or "value" not in spec:
            raise ValueError(f"series[{i}] needs at least 'table' and 'value'")
        name = _check_ident(spec.get("name") or f"s{i}", f"series[{i}].name")
        agg = spec.get("agg", "avg")
        if agg not in ("avg", "sum", "min", "max", "count", "median", "last", "first"):
            raise ValueError(f"series[{i}].agg {agg!r} not allowed")
        key = _key_expr(spec, on)
        where = f" WHERE {spec['where']}" if spec.get("where") else ""
        ctes.append(
            f"s{i} AS (SELECT {key} AS k, {agg}({spec['value']}) AS {name} "
            f"FROM {spec['table']}{where} GROUP BY 1)"
        )
        cols.append(name)

    # FULL OUTER chain: a gap in any one series surfaces as NULL rather than
    # silently dropping the period/geo via an inner join. The running COALESCE
    # keeps the key populated as later series join on.
    from_clause = "s0"
    seen = ["s0.k"]
    for i in range(1, len(series)):
        left = seen[0] if len(seen) == 1 else f"COALESCE({', '.join(seen)})"
        from_clause += f" FULL OUTER JOIN s{i} ON {left} = s{i}.k"
        seen.append(f"s{i}.k")
    key_sel = (seen[0] if len(seen) == 1 else f"COALESCE({', '.join(seen)})") + " AS key"

    with_clause = "WITH " + ", ".join(ctes)

    if stat is not None:
        a, b = cols[0], cols[1]
        if stat == "corr":
            expr = f"corr({a}, {b}) AS r, regr_count({a}, {b}) AS n"
        else:  # regr: model b ~ a
            expr = (f"regr_slope({b}, {a}) AS slope, regr_intercept({b}, {a}) AS intercept, "
                    f"regr_r2({b}, {a}) AS r2, regr_count({b}, {a}) AS n")
        return (f"{with_clause}, aligned AS "
                f"(SELECT {key_sel}, {', '.join(cols)} FROM {from_clause}) "
                f"SELECT {expr} FROM aligned")

    sql = (f"{with_clause} SELECT {key_sel}, {', '.join(cols)} "
           f"FROM {from_clause} ORDER BY key")
    if limit is not None:
        sql += f" FETCH FIRST {min(max(1, int(limit)), 5000)} ROWS ONLY"
    return sql


# ── resolve_geo ──────────────────────────────────────────────────────────────

def build_resolve_sql(term: str, level: str = "state",
                      within_state: Optional[str] = None, limit: int = 50) -> str:
    """
    Generate SQL that maps a free-text place `term` to canonical identifiers.

    level='state'  -> geo.state_ref  (state_fips, state_abbr, state_name)
    level='county' -> geo.counties   (county_fips, state_fips, county_name)
    level='zcta'   -> geo.zcta_ref   (zcta, latitude, longitude)
    """
    t = str(term).strip()
    if not t:
        raise ValueError("term must be non-empty")
    lit = _sql_str(t)
    like = _sql_str(f"%{t.lower()}%")
    cap = min(max(1, int(limit)), 500)

    if level == "state":
        # exact abbr (CA), exact 2-digit FIPS (06), or fuzzy name (california)
        return (
            "SELECT state_fips, state_abbr, state_name FROM geo.state_ref "
            f"WHERE lower(state_abbr) = lower({lit}) "
            f"OR state_fips = {lit} "
            f"OR lower(state_name) LIKE {like} "
            f"ORDER BY state_fips FETCH FIRST {cap} ROWS ONLY"
        )
    if level == "county":
        where = f"lower(county_name) LIKE {like} OR county_fips = {lit}"
        if within_state:
            where = f"({where}) AND state_fips = {_sql_str(str(within_state))}"
        return (
            "SELECT county_fips, state_fips, county_name FROM geo.counties "
            f"WHERE {where} "
            f"ORDER BY state_fips, county_name FETCH FIRST {cap} ROWS ONLY"
        )
    if level == "zcta":
        return (
            "SELECT zcta, latitude, longitude FROM geo.zcta_ref "
            f"WHERE zcta = {lit} FETCH FIRST {cap} ROWS ONLY"
        )
    raise ValueError(f"level must be 'state', 'county', or 'zcta'; got {level!r}")
