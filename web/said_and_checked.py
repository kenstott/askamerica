"""Said & Checked — renders said-and-checked-results/<date>/statements.json into one public
page per day. The file's schema and label vocabulary are defined in the calcite repo's
.claude/skills/askamerica-daily-eval/said-and-checked.md; validate() enforces them and stops the
build on anything outside it, so a malformed day is never published."""
import html
import json
import os
import re
import sys

KINDS = {
    "factual": "Factual claim",
    "opinion_or_prediction": "Opinion or prediction",
    "premised_prediction": "Premised prediction",
    "promise": "Promise",
    "personal_attack": "Personal attack",
}
# In ladder order, from best supported to ruled out; the header tally follows this order.
RESULTS = {
    "supported": "Supported",
    "unsettled": "Unsettled",
    "unsupported": "Unsupported",
    "contradicted": "Contradicted",
    "false": "False",
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
    ("Unsettled", "Evidence was found, but it does not decide the claim: it turns on how a law or "
                  "a loose term is read, or the evidence does not speak to the specific point."),
    ("Unsupported", "No evidence was found in the AskAmerica warehouse or any external factual "
                    "source. This does not mean the statement is false."),
    ("Contradicted", "A primary source, read directly, says something different on the specific "
                     "point, but some question remains open: an inquiry is unfinished, or the "
                     "source could be using a different definition or period."),
    ("False", "A settled official record, read directly, rules the statement out: a published "
              "measurement, no ordinary reading of the statement that fits it, and nothing "
              "pending that could change it."),
    ("Citejacked", "The speaker cites a source that does not say what the speaker claims."),
    ("Premised prediction", "An opinion or prediction that rests on a factual premise. The label "
                            "rates the premise only, never the opinion or prediction built on it."),
    ("Counter-statement", "A link to a statement by another speaker, or to an official document, that "
                          "directly addresses the same point and says otherwise. A link is not a "
                          "finding about which is right, and a rating shown beside a "
                          "counter-statement rates that statement only."),
    ("Not checkable", "An opinion, prediction, promise or personal attack. No data can settle it."),
]
# Kinds that carry a result. A premised prediction is an opinion or prediction that rests on a
# stated factual premise; its result rates the premise, never the opinion built on it.
CHECKED_KINDS = ("factual", "premised_prediction")
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
        if s["kind"] in CHECKED_KINDS:
            _require(s.get("result") in RESULTS, w, s["kind"] + " statement needs a result")
            if s["result"] != "not_checked":
                _require(isinstance(s.get("finding"), str) and s["finding"].strip(), w,
                         "finding is required for a checked statement")
        else:
            _require(s.get("result") is None, w,
                     "only factual statements and premised predictions carry a result")
        # Every checked statement states its test: what would make it true, what would make it
        # false, and what leaves it undeterminable. Written before the data is pulled.
        if s["kind"] in CHECKED_KINDS and s["result"] != "not_checked":
            _require(isinstance(s.get("test"), str) and s["test"].strip(), w,
                     "a checked statement needs a test (true if / false if / cannot be determined if)")
        if s["kind"] == "premised_prediction":
            _require(isinstance(s.get("premise"), str) and s["premise"].strip(), w,
                     "a premised_prediction needs a premise")
        else:
            _require(not s.get("premise"), w, "only a premised_prediction carries a premise")
        for cd in s.get("counter_documents") or []:
            _require(isinstance(cd, dict) and isinstance(cd.get("label"), str) and _is_url(cd.get("url")),
                     w, "counter_documents entries need label and url")
        for ev in s.get("evidence") or []:
            _require(isinstance(ev, dict) and isinstance(ev.get("label"), str) and _is_url(ev.get("url")),
                     w, "evidence entries need label and url")
            if ev.get("askamerica"):
                _require(ev["url"].startswith("https://askamerica.ai/catalog/"), w,
                         "an askamerica evidence entry links to the table's catalog page")
                _require(isinstance(ev.get("sql"), str) and ev["sql"].strip(), w,
                         "an askamerica evidence entry carries the sql that was run")
            else:
                _require("sql" not in ev, w, "only an askamerica evidence entry carries sql")
    # A counter-statement link is shown on both statements, so it must be recorded on both.
    by_id = {s["id"]: s for s in stmts}
    for s in stmts:
        for other in s.get("counter_statements") or []:
            w = "%s statement %r" % (where, s["id"])
            _require(other in by_id and other != s["id"], w, "counter_statements names no such statement")
            _require(s["id"] in (by_id[other].get("counter_statements") or []), w,
                     "counter-statement link to %r is not recorded on both statements" % other)
            _require(by_id[other]["speaker"] != s["speaker"], w,
                     "a counter-statement must come from a different speaker")


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


def is_checked(s):
    return s["kind"] in CHECKED_KINDS


def is_folded(s):
    """Shown inside the speaker's collapsed group: nothing was checked, nothing is linked to
    it and it carries no finding, so it adds a line to the record and no information."""
    return (not is_checked(s) and not s.get("counter_statements")
            and not s.get("counter_documents") and not s.get("finding"))


def counts(day):
    stmts = day["statements"]
    speakers = len({s["speaker"] for s in stmts})
    checked = sum(1 for s in stmts if is_checked(s))
    return len(stmts), speakers, checked


def result_summary(day):
    """'8 checked: 3 supported, 3 unsettled, 2 unsupported · 48 not checkable'."""
    stmts = day["statements"]
    tally = {}
    for s in stmts:
        if is_checked(s):
            tally[s["result"]] = tally.get(s["result"], 0) + 1
    parts = ["%d %s" % (tally[r], RESULTS[r].lower()) for r in RESULTS if r in tally]
    checked = sum(tally.values())
    out = "%d checked" % checked + (": " + ", ".join(parts) if parts else "")
    return out + " &middot; %d not checkable" % (len(stmts) - checked)


def _link(url, text):
    return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
            % (html.escape(url, quote=True), html.escape(text)))


def _excerpt(text, words=9):
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _statement_html(s, by_id):
    kind = s["kind"]
    if is_checked(s):
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
    if kind == "premised_prediction":
        finding = ('<p class="premise"><span>Premise rated</span> %s</p>'
                   % html.escape(s["premise"])) + finding
    if s.get("test"):
        finding += ('<p class="test"><span>How this was tested</span> %s</p>' % html.escape(s["test"]))
    evidence = ""
    if s.get("evidence"):
        # AskAmerica's own warehouse queries are listed first and marked, including a query
        # that only bounds the answer.
        # Each of those carries a [SQL] button that shows the exact query that was run.
        ordered = sorted(s["evidence"], key=lambda e: not e.get("askamerica"))
        parts, panels = [], []
        for i, e in enumerate(ordered):
            part = _link(e["url"], e["label"])
            if e.get("askamerica"):
                panel_id = "sql-%d-%d" % (s["id"], i)
                part = ('<span class="aa">AskAmerica data</span> %s '
                        '<button type="button" class="sqlbtn" aria-expanded="false" '
                        'aria-controls="%s">[SQL]</button>' % (part, panel_id))
                panels.append('<pre class="sql" id="%s" hidden>%s</pre>'
                              % (panel_id, html.escape(e["sql"].strip())))
            parts.append(part)
        evidence = '<p class="evidence">Evidence: %s</p>%s' % (", ".join(parts), "".join(panels))
    counters = []
    for other_id in s.get("counter_statements") or []:
        o = by_id[other_id]
        # When the counter-statement was checked, its rating travels with the link: a bare
        # opinion answered by a statement whose premise was tested is the informative case.
        rating = ""
        if is_checked(o):
            what = "premise " if o["kind"] == "premised_prediction" else ""
            rating = ' <span class="rating %s">(%s%s)</span>' % (
                "r-" + o["result"], what, html.escape(RESULTS[o["result"]].lower()))
        counters.append('<a href="#s%d">%s: \u201c%s\u201d</a>%s'
                        % (other_id, html.escape(o["speaker"]), html.escape(_excerpt(o["quote"])),
                           rating))
    for cd in s.get("counter_documents") or []:
        counters.append(_link(cd["url"], cd["label"]))
    counter = ""
    if counters:
        counter = ('<p class="counter"><span>Counter-statement</span> %s</p>'
                   % " &middot; ".join(counters))
    return (
        '<div class="stmt" id="s%d">'
        '<div class="tags"><span class="badge %s">%s</span>'
        '<span class="kind">%s</span></div>'
        '<p class="context">%s</p>'
        '<blockquote>%s</blockquote>%s%s%s'
        '<p class="src">%s</p></div>'
        % (s["id"], badge_class, html.escape(badge), html.escape(KINDS[kind]),
           html.escape(s["context"]), html.escape(s["quote"]), finding, evidence, counter, src_line)
    )


# Opens a collapsed group when a counter-statement link points at a statement inside it.
OPEN_TARGET_SCRIPT = """<script>
(function () {
  function reveal() {
    var id = location.hash.slice(1);
    var el = id && document.getElementById(id);
    if (!el) { return; }
    for (var p = el.parentElement; p; p = p.parentElement) {
      if (p.tagName === "DETAILS") { p.open = true; }
    }
    el.scrollIntoView();
  }
  window.addEventListener("hashchange", reveal);
  reveal();
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest && ev.target.closest(".sqlbtn");
    if (!b) { return; }
    var panel = document.getElementById(b.getAttribute("aria-controls"));
    panel.hidden = !panel.hidden;
    b.setAttribute("aria-expanded", String(!panel.hidden));
  });
})();
</script>"""


def render_day(day, back_banner):
    by_id = {s["id"]: s for s in day["statements"]}
    by_speaker = {}
    for s in day["statements"]:
        by_speaker.setdefault(s["speaker"], []).append(s)
    sections = []
    for name in sorted(by_speaker, key=lambda n: n.split()[-1].lower()):
        items = by_speaker[name]
        first = items[0]
        party = " (%s)" % html.escape(first["party"]) if first.get("party") else ""
        shown = [s for s in items if not is_folded(s)]
        folded = [s for s in items if is_folded(s)]
        body = "".join(_statement_html(s, by_id) for s in shown)
        if folded:
            body += (
                '<details class="fold"><summary>%d statement%s not checkable</summary>%s</details>'
                % (len(folded), "" if len(folded) == 1 else "s",
                   "".join(_statement_html(s, by_id) for s in folded))
            )
        sections.append(
            '<section><h2>%s%s</h2><p class="office">%s</p>%s</section>'
            % (html.escape(name), party, html.escape(first["office"]), body)
        )
    n, speakers, _ = counts(day)
    summary = result_summary(day)
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
  .meta {{ color: var(--text-dim); font-size: 12px; margin-bottom: 0.3rem; }}
  .lede {{ max-width: 68ch; }}
  .lede p {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
             Arial, sans-serif; font-size: 16px; line-height: 1.65; color: var(--text);
             margin-bottom: 1rem; }}
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
  .badge.r-false {{ color: #080b0f; background: #e5534b; border-color: #e5534b; }}
  .rating.r-false {{ color: #e5534b; font-weight: 700; }}
  .r-unsupported {{ color: #c69026; }} .r-citejacked {{ color: #b083f0; }}
  .r-unsettled {{ color: #6cb6ff; }}
  .r-not_checked, .r-na {{ color: var(--text-dim); }}
  .kind {{ color: var(--text-dim); font-size: 11px; }}
  blockquote {{ border-left: 2px solid var(--amber); padding-left: 0.9rem; color: var(--white);
                overflow-wrap: anywhere; }}
  .context {{ color: var(--text-dim); font-size: 12px; margin-bottom: 0.4rem; }}
  .premise, .counter {{ margin-top: 0.7rem; font-size: 13px; overflow-wrap: anywhere; }}
  .counter span.rating {{ font-size: 12px; letter-spacing: 0; text-transform: none; margin: 0 0 0 0.3rem; }}
  .test {{ margin-top: 0.6rem; font-size: 12px; color: var(--text-dim); overflow-wrap: anywhere; }}
  .test > span {{ color: var(--text-dim); font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
                  border: 1px solid var(--border); padding: 1px 6px; margin-right: 0.4rem; }}
  .premise > span, .counter > span:first-child {{ color: var(--amber); font-size: 11px; letter-spacing: 0.06em;
                                  text-transform: uppercase; margin-right: 0.4rem; }}
  details.fold {{ margin: 0 0 1rem; padding: 0.6rem 0.9rem; }}
  details.fold[open] summary {{ margin-bottom: 1rem; }}
  details.fold .stmt:last-child {{ border-bottom: 0; margin-bottom: 0; padding-bottom: 0.2rem; }}
  .stmt:target {{ outline: 1px solid var(--amber); outline-offset: 8px; }}
  .tally {{ color: var(--text); font-size: 13px; margin-bottom: 1.5rem; }}
  .evidence .aa {{ color: var(--bg); background: var(--amber); font-size: 10px; letter-spacing: 0.06em;
                  text-transform: uppercase; padding: 1px 6px; margin-right: 0.2rem; }}
  .sqlbtn {{ font: inherit; font-size: 11px; color: var(--amber); background: none; border: 0;
            padding: 0 0.15rem; cursor: pointer; }}
  .sqlbtn:hover, .sqlbtn[aria-expanded="true"] {{ text-decoration: underline; }}
  pre.sql {{ margin: 0.4rem 0 0; padding: 0.6rem 0.8rem; border: 1px solid var(--border);
            font-size: 12px; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere;
            color: var(--text); }}
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
    from {speakers} speaker{"s" if speakers != 1 else ""}</p>
  <p class="tally">{summary}</p>
  <div class="lede">{lede}</div>
  <details>
    <summary>How to read this page</summary>
    <dl>{legend}</dl>
    <p class="rule">Every statement is listed, whatever its kind. There are no scores and no
      totals per person. Statements that could not be checked are folded under each speaker.
      Selection: {html.escape(day["selection_rule"])}</p>
  </details>
  {"".join(sections)}
</main>
{OPEN_TARGET_SCRIPT}
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


def main(argv):
    """python3 said_and_checked.py <statements.json>: validate one day's file without building.
    The unattended daily run uses this to decide whether a day is published or held."""
    if len(argv) != 2:
        sys.exit("usage: said_and_checked.py <statements.json>")
    path = argv[1]
    with open(path) as fh:
        doc = json.load(fh)
    try:
        validate(doc, path)
        _require(doc["date"] == os.path.basename(os.path.dirname(os.path.abspath(path))), path,
                 "date does not match its directory")
    except InvalidStatements as e:
        sys.exit("INVALID %s" % e)
    n, speakers, _ = counts(doc)
    print("VALID %s: %d statements, %d speakers; %s" % (path, n, speakers, result_summary(doc)))


if __name__ == "__main__":
    main(sys.argv)
