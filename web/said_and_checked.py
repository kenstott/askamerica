"""Said & Checked — renders said-and-checked-results/<date>/statements.json into one public
page per day. The file's schema and label vocabulary are defined in the calcite repo's
.claude/skills/askamerica-daily-eval/said-and-checked.md; validate() enforces them and stops the
build on anything outside it, so a malformed day is never published."""
import html
import json
import os
import re

KINDS = {
    "factual": "Factual claim",
    "opinion_or_prediction": "Opinion or prediction",
    "promise": "Promise",
    "personal_attack": "Personal attack",
}
RESULTS = {
    "supported": "Supported",
    "contradicted": "Contradicted",
    "unsupported": "Unsupported",
    "citejacked": "Citejacked",
    "not_checked": "Not yet checked",
}
SOURCE_STATUS = {
    "verbatim": "Original found, quoted verbatim",
    "paraphrased": "Original found, paraphrased by the outlet",
    "truncated": "Original found, context cut by the outlet",
    "not_found": "Original not found; wording as reported",
}
LEGEND = [
    ("Supported", "Warehouse or external primary data confirms the statement."),
    ("Contradicted", "Data exists and says something different."),
    ("Unsupported", "No evidence was found in the AskAmerica warehouse or any external factual "
                    "source. This does not mean the statement is false."),
    ("Citejacked", "The speaker cites a source that does not say what the speaker claims."),
    ("Not checkable", "An opinion, prediction, promise or personal attack. No data can settle it."),
]
SLUG_PREFIX = "said-and-checked-"


class InvalidStatements(Exception):
    pass


def _require(cond, where, msg):
    if not cond:
        raise InvalidStatements("%s: %s" % (where, msg))


def _is_url(v):
    return isinstance(v, str) and re.match(r"https?://", v) is not None


def validate(doc, where):
    _require(isinstance(doc, dict), where, "top level must be an object")
    _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(doc.get("date", ""))), where, "bad date")
    _require(isinstance(doc.get("selection_rule"), str) and doc["selection_rule"].strip(),
             where, "selection_rule is required")
    lede = doc.get("lede")
    _require(isinstance(lede, list) and lede and all(isinstance(p, str) and p.strip() for p in lede),
             where, "lede must be a non-empty list of paragraphs")
    stmts = doc.get("statements")
    _require(isinstance(stmts, list) and stmts, where, "statements must be a non-empty list")
    seen = set()
    for s in stmts:
        w = "%s statement %r" % (where, s.get("id") if isinstance(s, dict) else s)
        _require(isinstance(s, dict), w, "must be an object")
        _require(isinstance(s.get("id"), int) and s["id"] not in seen, w, "id missing or repeated")
        seen.add(s["id"])
        for field in ("speaker", "office", "quote", "context"):
            _require(isinstance(s.get(field), str) and s[field].strip(), w, field + " is required")
        rb = s.get("reported_by")
        _require(isinstance(rb, dict) and isinstance(rb.get("outlet"), str) and _is_url(rb.get("url")),
                 w, "reported_by needs outlet and url")
        src = s.get("source")
        _require(isinstance(src, dict) and src.get("status") in SOURCE_STATUS, w, "bad source.status")
        if src["status"] == "not_found":
            _require(src.get("url") is None, w, "source.url must be null when not_found")
        else:
            _require(_is_url(src.get("url")), w, "source.url is required when the original was found")
        _require(s.get("kind") in KINDS, w, "bad kind")
        if s["kind"] == "factual":
            _require(s.get("result") in RESULTS, w, "factual statement needs a result")
            if s["result"] != "not_checked":
                _require(isinstance(s.get("finding"), str) and s["finding"].strip(), w,
                         "finding is required for a checked factual statement")
        else:
            _require(s.get("result") is None, w, "only factual statements carry a result")
        for ev in s.get("evidence") or []:
            _require(isinstance(ev, dict) and isinstance(ev.get("label"), str) and _is_url(ev.get("url")),
                     w, "evidence entries need label and url")


def load_days(root):
    """Every said-and-checked-results/<date>/statements.json, validated, newest first."""
    if not os.path.isdir(root):
        return []
    days = []
    for d in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, d, "statements.json")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not os.path.isfile(path):
            continue
        with open(path) as fh:
            doc = json.load(fh)
        validate(doc, path)
        _require(doc["date"] == d, path, "date does not match its directory")
        days.append(doc)
    return days


def slug(day):
    return SLUG_PREFIX + day["date"]


def counts(day):
    stmts = day["statements"]
    speakers = len({s["speaker"] for s in stmts})
    factual = sum(1 for s in stmts if s["kind"] == "factual")
    return len(stmts), speakers, factual


def _link(url, text):
    return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
            % (html.escape(url, quote=True), html.escape(text)))


def _statement_html(s):
    kind = s["kind"]
    if kind == "factual":
        badge_class, badge = "r-" + s["result"], RESULTS[s["result"]]
    else:
        badge_class, badge = "r-na", "Not checkable"
    src = s["source"]
    src_line = html.escape(SOURCE_STATUS[src["status"]])
    if src.get("url"):
        src_line += " &middot; " + _link(src["url"], "original")
    src_line += " &middot; reported by " + _link(s["reported_by"]["url"], s["reported_by"]["outlet"])
    if src.get("note"):
        src_line += '<br>' + html.escape(src["note"])
    finding = ('<p class="finding">%s</p>' % html.escape(s["finding"])) if s.get("finding") else ""
    evidence = ""
    if s.get("evidence"):
        evidence = '<p class="evidence">Evidence: %s</p>' % ", ".join(
            _link(e["url"], e["label"]) for e in s["evidence"])
    return (
        '<div class="stmt">'
        '<div class="tags"><span class="badge %s">%s</span>'
        '<span class="kind">%s</span></div>'
        '<p class="context">%s</p>'
        '<blockquote>%s</blockquote>%s%s'
        '<p class="src">%s</p></div>'
        % (badge_class, html.escape(badge), html.escape(KINDS[kind]),
           html.escape(s["context"]), html.escape(s["quote"]), finding, evidence, src_line)
    )


def render_day(day, back_banner):
    by_speaker = {}
    for s in day["statements"]:
        by_speaker.setdefault(s["speaker"], []).append(s)
    sections = []
    for name in sorted(by_speaker, key=lambda n: n.split()[-1].lower()):
        items = by_speaker[name]
        first = items[0]
        party = " (%s)" % html.escape(first["party"]) if first.get("party") else ""
        sections.append(
            '<section><h2>%s%s</h2><p class="office">%s</p>%s</section>'
            % (html.escape(name), party, html.escape(first["office"]),
               "".join(_statement_html(s) for s in items))
        )
    n, speakers, factual = counts(day)
    lede = "".join("<p>%s</p>" % html.escape(p) for p in day["lede"])
    legend = "".join("<dt>%s</dt><dd>%s</dd>" % (html.escape(t), html.escape(d)) for t, d in LEGEND)
    title = "Said & Checked — %s" % day["date"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} — AskAmerica</title>
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #080b0f; --bg2: #0d1117; --border: #1e2d3d; --amber: #e8a24a;
    --text: #cdd9e5; --text-dim: #768390; --white: #f0f6fc;
    --mono: 'JetBrains Mono', monospace; --serif: 'Instrument Serif', serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: var(--mono);
          font-size: 14px; line-height: 1.7; }}
  main {{ max-width: 820px; margin: 0 auto; padding: 3rem 1rem 6rem; }}
  a {{ color: var(--amber); }}
  .label {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--amber); }}
  h1 {{ font-family: var(--serif); font-size: clamp(1.8rem, 5vw, 2.6rem); font-weight: 400;
        color: var(--white); margin: 0.4rem 0 0.4rem; }}
  .meta {{ color: var(--text-dim); font-size: 12px; margin-bottom: 1.5rem; }}
  .lede p {{ font-family: var(--serif); font-size: 1.15rem; line-height: 1.55; color: var(--white);
             margin-bottom: 0.9rem; }}
  details {{ border: 1px solid var(--border); background: var(--bg2); padding: 0.8rem 1rem;
             margin: 1.5rem 0 2.5rem; font-size: 12px; }}
  summary {{ cursor: pointer; color: var(--text-dim); }}
  dl {{ margin-top: 0.8rem; }}
  dt {{ color: var(--white); margin-top: 0.5rem; }}
  dd {{ color: var(--text-dim); }}
  .rule {{ color: var(--text-dim); margin-top: 0.8rem; }}
  section {{ margin-bottom: 2.5rem; }}
  h2 {{ font-family: var(--serif); font-weight: 400; font-size: 1.5rem; color: var(--white); }}
  .office {{ color: var(--text-dim); font-size: 12px; border-bottom: 1px solid var(--border);
             padding-bottom: 0.5rem; margin-bottom: 1rem; }}
  .stmt {{ padding: 0 0 1.2rem; margin-bottom: 1.2rem; border-bottom: 1px solid var(--border); }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; margin-bottom: 0.5rem; }}
  .badge {{ font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
            padding: 2px 8px; border: 1px solid currentColor; }}
  .r-supported {{ color: #57ab5a; }} .r-contradicted {{ color: #e5534b; }}
  .r-unsupported {{ color: #c69026; }} .r-citejacked {{ color: #b083f0; }}
  .r-not_checked, .r-na {{ color: var(--text-dim); }}
  .kind {{ color: var(--text-dim); font-size: 11px; }}
  blockquote {{ border-left: 2px solid var(--amber); padding-left: 0.9rem; color: var(--white);
                overflow-wrap: anywhere; }}
  .context {{ color: var(--text-dim); font-size: 12px; margin-bottom: 0.4rem; }}
  .finding {{ margin-top: 0.6rem; }}
  .evidence, .src {{ margin-top: 0.4rem; font-size: 12px; color: var(--text-dim);
                     overflow-wrap: anywhere; }}
</style>
</head>
<body>
{back_banner}
<main>
  <div class="label">Said &amp; Checked</div>
  <h1>What officeholders said, and what the data shows</h1>
  <p class="meta">{html.escape(day["date"])} &middot; {n} statement{"s" if n != 1 else ""}
    from {speakers} speaker{"s" if speakers != 1 else ""} &middot; {factual} factual</p>
  <div class="lede">{lede}</div>
  <details>
    <summary>How to read this page</summary>
    <dl>{legend}</dl>
    <p class="rule">Every statement is listed, whatever its kind. There are no scores and no
      totals per person. Selection: {html.escape(day["selection_rule"])}</p>
  </details>
  {"".join(sections)}
</main>
</body>
</html>
"""


def index_rows(days):
    rows = []
    for day in days:
        n, speakers, _ = counts(day)
        rows.append(
            f'<li class="study-row"><a href="/studies/{slug(day)}/">What officeholders said on '
            f'{html.escape(day["date"])}</a><span class="study-date">{n} statements &middot; '
            f'{speakers} speakers</span></li>'
        )
    return rows
