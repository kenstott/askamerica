#!/usr/bin/env python3
"""Generate the AskAmerica data-catalog MkDocs site from the govdata schema YAMLs.

Reads every govdata <source>/<source>-schema.yaml (the authored catalog: schema /
table / column names + `comment:` descriptions) and writes:
  - docs/index.md              overview + schema index
  - docs/schemas/<schema>.md   one page per schema, a table per dataset with columns
  - mkdocs.yml                 site config + nav

Run:  <venv>/bin/python catalog/gen_docs.py   then  <venv>/bin/mkdocs build
"""
import glob
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
GOVDATA = os.environ.get(
    "GOVDATA_RESOURCES",
    "/home/kstott/calcite/govdata/src/main/resources",
)
DOCS = os.path.join(HERE, "docs")

ICONS = {
    "sec": "🏦", "fec": "🗳️", "weather": "🌦️", "census": "📊", "econ": "📈",
    "fedregister": "🔵", "cyber_vuln": "🔒", "cyber_threat": "⚠️", "energy": "⚡",
    "health": "🏥", "edu": "🎓", "crime": "🚨", "geo": "🗺️", "lands": "🌲",
    "patents": "💡", "cftc": "📉", "ref": "📋", "econ_reference": "🔤",
    "ag": "🚜", "disasters": "🌀", "environment": "🌎", "housing": "🏘️",
    "transport": "🚗", "fiscal": "💵", "research": "🔬",
}


def schema_name(d, path):
    sn = d.get("schemaName")
    if isinstance(sn, str):
        m = re.search(r"\$\{SCHEMA_NAME:([^}]+)\}", sn)
        if m:
            return m.group(1)
        if sn and "$" not in sn:
            return sn
    return os.path.basename(path).replace("-schema.yaml", "").replace("-", "_")


def clean(s):
    return " ".join(str(s).split()) if s else ""


def esc(s):
    return clean(s).replace("|", "\\|")


def col_code(name):
    """Render an identifier so it wraps only at underscores, not mid-token."""
    return "<code>" + esc(name).replace("_", "_<wbr>") + "</code>"


EXTRA_CSS = """/* snake_case identifiers break only at the <wbr> after each underscore */
.md-typeset table td code {
  word-break: normal;
  overflow-wrap: normal;
  white-space: normal;
}
"""


def load():
    files = sorted(glob.glob(os.path.join(GOVDATA, "*", "*-schema.yaml")))
    files = [f for f in files if "deprecated" not in f]
    cat = []
    for f in files:
        d = yaml.safe_load(open(f))
        sch = {"schema": schema_name(d, f), "comment": clean(d.get("comment")), "tables": []}
        seen = set()
        for key, ttype in (("tables", "table"), ("partitionedTables", "table"), ("views", "view")):
            for t in (d.get(key) or []):
                name = t.get("name")
                if not name or name in seen:
                    continue
                seen.add(name)
                cols = [{"name": c.get("name"), "type": c.get("type"),
                         "nullable": c.get("nullable", True), "comment": clean(c.get("comment"))}
                        for c in (t.get("columns") or [])]
                sch["tables"].append({"name": name, "type": ttype,
                                      "comment": clean(t.get("comment")), "columns": cols})
        cat.append(sch)
    return cat


def write_schema_page(sch):
    icon = ICONS.get(sch["schema"], "📁")
    ncol = sum(len(t["columns"]) for t in sch["tables"])
    lines = [f"# {icon} `{sch['schema']}`", ""]
    if sch["comment"]:
        lines += [sch["comment"], ""]
    lines += [f"**{len(sch['tables'])} datasets · {ncol} columns**", ""]
    for t in sch["tables"]:
        badge = "view" if t["type"] == "view" else "table"
        lines += [f"## {t['name']} <small>· {badge}</small>", ""]
        if t["comment"]:
            lines += [t["comment"], ""]
        if t["columns"]:
            lines += ["| Column | Type | Null | Description |",
                      "|---|---|:--:|---|"]
            for c in t["columns"]:
                null = "yes" if c.get("nullable", True) else "no"
                lines.append(
                    f"| {col_code(c['name'])} | {esc(c['type'] or '')} | {null} | {esc(c['comment'])} |")
            lines.append("")
        else:
            lines += ["*View — columns are resolved by the query engine at runtime.*", ""]
    path = os.path.join(DOCS, "schemas", f"{sch['schema']}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("\n".join(lines))


def write_index(cat):
    total_t = sum(len(s["tables"]) for s in cat)
    total_c = sum(len(t["columns"]) for s in cat for t in s["tables"])
    lines = [
        "# AskAmerica Data Catalog", "",
        "US government data as a service — query SEC filings, FEC campaign finance, "
        "Census, economic indicators, weather, and more with one API key, from Claude "
        "Desktop or plain SQL.", "",
        f"**{len(cat)} schemas · {total_t} datasets · {total_c:,} columns** — "
        "cross-linked by legal entity, geography, and time.", "",
        '<p><a href="https://askamerica.ai/#signup" class="md-button md-button--primary">'
        "Get a free API key</a> "
        '<a href="https://askamerica.ai/#download" class="md-button">Download &amp; connect</a></p>',
        "",
        "## Schemas", "",
        "| Schema | Datasets | Description |",
        "|---|--:|---|",
    ]
    for s in sorted(cat, key=lambda x: x["schema"]):
        icon = ICONS.get(s["schema"], "📁")
        desc = esc(s["comment"])
        if len(desc) > 160:
            desc = desc[:157] + "…"
        lines.append(f"| {icon} [`{s['schema']}`](schemas/{s['schema']}.md) "
                     f"| {len(s['tables'])} | {desc} |")
    lines.append("")
    open(os.path.join(DOCS, "index.md"), "w").write("\n".join(lines))


def write_mkdocs_yml(cat):
    nav = ["  - Overview: index.md", "  - Schemas:"]
    for s in sorted(cat, key=lambda x: x["schema"]):
        nav.append(f"      - '{s['schema']}': schemas/{s['schema']}.md")
    cfg = f"""site_name: AskAmerica Data Catalog
site_url: https://askamerica.ai/catalog/
site_description: >
  Full schema/table/column data dictionary for AskAmerica — {len(cat)} schemas of
  US government data with descriptions.
repo_url: https://github.com/kenstott/askamerica
edit_uri: ""
use_directory_urls: true

extra_css:
  - stylesheets/extra.css

theme:
  name: material
  palette:
    - scheme: slate
      primary: black
      accent: amber
      toggle:
        icon: material/weather-night
        name: Light mode
    - scheme: default
      primary: black
      accent: amber
      toggle:
        icon: material/weather-sunny
        name: Dark mode
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.top
    - navigation.sections
    - search.suggest
    - search.highlight
    - content.code.copy
    - toc.follow
  font:
    text: Inter
    code: JetBrains Mono

markdown_extensions:
  - tables
  - admonition
  - toc:
      permalink: true
  - attr_list
  - md_in_html

plugins:
  - search

extra:
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/kenstott/askamerica

nav:
{chr(10).join(nav)}
"""
    open(os.path.join(HERE, "mkdocs.yml"), "w").write(cfg)


def main():
    cat = load()
    os.makedirs(os.path.join(DOCS, "schemas"), exist_ok=True)
    css_dir = os.path.join(DOCS, "stylesheets")
    os.makedirs(css_dir, exist_ok=True)
    open(os.path.join(css_dir, "extra.css"), "w").write(EXTRA_CSS)
    write_index(cat)
    for s in cat:
        write_schema_page(s)
    write_mkdocs_yml(cat)
    t = sum(len(s["tables"]) for s in cat)
    c = sum(len(x["columns"]) for s in cat for x in s["tables"])
    print(f"generated: {len(cat)} schema pages, {t} datasets, {c} columns")


if __name__ == "__main__":
    main()
