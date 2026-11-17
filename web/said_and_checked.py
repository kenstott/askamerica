"""Said & Checked — renders said-and-checked-results/<date>/statements.json into one public
page per day. The file's schema and label vocabulary are defined in the calcite repo's
.claude/skills/askamerica-daily-eval/said-and-checked.md; validate() enforces them and stops the
build on anything outside it, so a malformed day is never published."""
import html
import json
import os
import re
import sys

import topics

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
    ("Said more than once", "When a speaker makes the same claim several times in similar words, it is "
                            "listed once, with the other wordings and where each was said shown "
                            "beneath it. Versions that differ on a figure, date or cause stay "
                            "separate."),
    ("Contradicts own statement", "A link between two factual statements by the same speaker that "
                                  "cannot both be true on the same specific point. A link is not "
                                  "a finding about which one is right; each statement keeps its "
                                  "own label."),
    ("Not checkable", "An opinion, prediction, promise or personal attack. No data can settle it."),
]
# Kinds that carry a result. A premised prediction is an opinion or prediction that rests on a
# stated factual premise; its result rates the premise, never the opinion built on it.
CHECKED_KINDS = ("factual", "premised_prediction")
SLUG_PREFIX = "said-and-checked-"
SAID_ARCHIVE_SLUG = "said-and-checked-archive"
# Postal codes for speaker_state and about_states: the 50 states and DC.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


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
        for field in ("speaker", "office", "quote", "context", "topic"):
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
        _require(s.get("broad_topic") in topics.SAID_TOPICS, w,
                 "broad_topic must be one of topics.SAID_TOPICS")
        # speaker_state: the state a member of Congress or governor represents, else null.
        # about_states: the states the statement is mainly about (possibly none).
        _require("speaker_state" in s and (s["speaker_state"] is None
                                           or s["speaker_state"] in US_STATES), w,
                 "speaker_state must be a state postal code or null")
        ab = s.get("about_states")
        _require(isinstance(ab, list) and all(c in US_STATES for c in ab) and len(set(ab)) == len(ab),
                 w, "about_states must be a list of distinct state postal codes")
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
        # Other places the same speaker made the same claim, condensed into this entry.
        for alt in s.get("also_said") or []:
            _require(isinstance(alt, dict) and isinstance(alt.get("quote"), str) and alt["quote"].strip()
                     and isinstance(alt.get("outlet"), str) and _is_url(alt.get("url")), w,
                     "also_said entries need quote, outlet and url")
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
        # An internal contradiction pairs two factual statements by the same speaker.
        for other in s.get("self_contradictions") or []:
            _require(other in by_id and other != s["id"], w,
                     "self_contradictions names no such statement")
            _require(s["id"] in (by_id[other].get("self_contradictions") or []), w,
                     "internal-contradiction link to %r is not recorded on both statements" % other)
            _require(by_id[other]["speaker"] == s["speaker"], w,
                     "an internal contradiction pairs two statements by the same speaker")
            _require(s["kind"] == "factual" and by_id[other]["kind"] == "factual", w,
                     "an internal contradiction pairs two factual statements")


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
    return s["kind"] in CHECKED_KINDS and s.get("result") != "not_checked"


def is_waiting(s):
    """Checkable, but over the day's check cap: shown as "not yet checked"."""
    return s["kind"] in CHECKED_KINDS and s.get("result") == "not_checked"


def is_folded(s):
    """Shown inside the speaker's collapsed group: nothing was checked, nothing is linked to
    it and it carries no finding, so it adds a line to the record and no information."""
    return (not is_checked(s) and not s.get("counter_statements")
            and not s.get("self_contradictions")
            and not s.get("counter_documents") and not s.get("finding"))


def counts(day):
    stmts = day["statements"]
    speakers = len({s["speaker"] for s in stmts})
    checked = sum(1 for s in stmts if is_checked(s))
    return len(stmts), speakers, checked


def result_summary(day):
    """'8 checked: 3 supported, 3 unsettled, 2 unsupported · 48 not checkable'."""
    return statements_summary(day["statements"])


def statements_summary(stmts):
    """The same line for any list of statements: the whole day, or one speaker."""
    tally = {}
    for s in stmts:
        if is_checked(s):
            tally[s["result"]] = tally.get(s["result"], 0) + 1
    parts = ["%d %s" % (tally[r], RESULTS[r].lower()) for r in RESULTS if r in tally]
    checked = sum(tally.values())
    out = "%d checked" % checked + (": " + ", ".join(parts) if parts else "")
    waiting = sum(1 for s in stmts if is_waiting(s))
    if waiting:
        out += " &middot; %d not yet checked" % waiting
    return out + " &middot; %d not checkable" % (len(stmts) - checked - waiting)


def _link(url, text):
    return ('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>'
            % (html.escape(url, quote=True), html.escape(text)))


def _excerpt(text, words=9):
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _statement_html(s, by_id):
    kind = s["kind"]
    if is_checked(s) or is_waiting(s):
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
    also = ""
    if s.get("also_said"):
        also = ('<details class="also"><summary>Said %d more time%s in similar words</summary><ul>%s</ul></details>'
                % (len(s["also_said"]), "" if len(s["also_said"]) == 1 else "s",
                   "".join('<li>\u201c%s\u201d <span class="where">%s</span></li>'
                           % (html.escape(a["quote"]), _link(a["url"], a["outlet"]))
                           for a in s["also_said"])))
    own = [
        '<a href="#s%d">\u201c%s\u201d</a> <span class="where">(%s)</span>'
        % (other_id, html.escape(_excerpt(by_id[other_id]["quote"])),
           html.escape(by_id[other_id]["reported_by"]["outlet"]))
        for other_id in s.get("self_contradictions") or []]
    if own:
        # Not a rating: it says only that the two statements cannot both be true.
        counter += ('<p class="counter own"><span>Contradicts own statement</span> %s</p>'
                    % " &middot; ".join(own))
    return (
        '<div class="stmt" id="s%d">'
        '<div class="tags"><span class="badge %s">%s</span>'
        '<span class="kind">%s</span></div>'
        '<p class="context">%s</p>'
        '<blockquote>%s</blockquote>%s%s%s%s'
        '<p class="src">%s</p></div>'
        % (s["id"], badge_class, html.escape(badge), html.escape(KINDS[kind]),
           html.escape(s["context"]), html.escape(s["quote"]), also, finding, evidence, counter,
           src_line)
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
  // Each statement exists once. Changing the view moves it into that view's slots.
  function show(name) {
    var views = document.querySelectorAll(".view");
    for (var i = 0; i < views.length; i++) { views[i].hidden = views[i].id !== "view-" + name; }
    var slots = document.querySelectorAll("#view-" + name + " .slot");
    for (var j = 0; j < slots.length; j++) {
      var ids = slots[j].getAttribute("data-ids").split(",");
      for (var k = 0; k < ids.length; k++) {
        slots[j].appendChild(document.getElementById("s" + ids[k]));
      }
    }
    var btns = document.querySelectorAll(".viewbtn");
    for (var m = 0; m < btns.length; m++) {
      btns[m].setAttribute("aria-pressed", String(btns[m].getAttribute("data-view") === name));
    }
    var all = document.querySelector(".openall");
    all.setAttribute("aria-expanded", "false");
    all.textContent = "Open all";
  }
  window.addEventListener("hashchange", reveal);
  reveal();
  document.addEventListener("click", function (ev) {
    var all = ev.target.closest && ev.target.closest(".openall");
    if (all) {
      var open = all.getAttribute("aria-expanded") !== "true";
      var people = document.querySelectorAll(".view:not([hidden]) details");
      for (var i = 0; i < people.length; i++) { people[i].open = open; }
      all.setAttribute("aria-expanded", String(open));
      all.textContent = open ? "Close all" : "Open all";
      return;
    }
    var v = ev.target.closest && ev.target.closest(".viewbtn");
    if (v) { show(v.getAttribute("data-view")); return; }
    var b = ev.target.closest && ev.target.closest(".sqlbtn");
    if (!b) { return; }
    var panel = document.getElementById(b.getAttribute("aria-controls"));
    panel.hidden = !panel.hidden;
    b.setAttribute("aria-expanded", String(!panel.hidden));
  });
})();
</script>"""


OTHER_TOPIC = "Other"


def topic_of(day):
    """Statement id -> the topic it is listed under. A topic with a single statement on the
    page is listed under Other, so every group on the page holds more than one statement
    or is Other."""
    n = {}
    for s in day["statements"]:
        n[s["topic"]] = n.get(s["topic"], 0) + 1
    return {s["id"]: (s["topic"] if n[s["topic"]] > 1 else OTHER_TOPIC) for s in day["statements"]}


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _leaf_html(items, by_id, fill):
    """The statements of one inner group: those with something to show, then the collapsed
    groups. Statements are written once, in the speaker view (fill). The topic view gets empty
    slots naming the same statements, and the page script moves them when the view changes."""
    def slot(group):
        ids = ",".join(str(s["id"]) for s in group)
        inner = "".join(_statement_html(s, by_id) for s in group) if fill else ""
        return '<div class="slot" data-ids="%s">%s</div>' % (ids, inner)
    shown = [s for s in items if not is_folded(s)]
    folded = [s for s in items if is_folded(s)]
    out = slot(shown) if shown else ""
    # Two collapsed groups: statements waiting for a check, then those no data can settle.
    for label, group in (("not yet checked", [s for s in folded if is_waiting(s)]),
                         ("not checkable", [s for s in folded if not is_waiting(s)])):
        if group:
            out += ('<details class="fold"><summary>%s %s</summary>%s</details>'
                    % (_plural(len(group), "statement"), label, slot(group)))
    return out


def _speaker_key(name):
    return name.split()[-1].lower()


def _speaker_label(s):
    return html.escape(s["speaker"]) + (" (%s)" % html.escape(s["party"]) if s.get("party") else "")


def _views_html(day):
    """Two orderings of the same statements, each two levels deep: speaker then topic, and
    topic then speaker. Every group is collapsed and its heading carries its own counts."""
    stmts = day["statements"]
    by_id = {s["id"]: s for s in stmts}
    topic = topic_of(day)

    def topic_order(items):
        """Largest topic first, Other last."""
        size = {}
        for s in items:
            size[topic[s["id"]]] = size.get(topic[s["id"]], 0) + 1
        return sorted(size, key=lambda t: (t == OTHER_TOPIC, -size[t], t))

    def sub(title, items, fill):
        return ('<details class="sub"><summary><h3>%s</h3><p class="ptally">%s &middot; %s</p>'
                '</summary>%s</details>'
                % (title, _plural(len(items), "statement"), statements_summary(items),
                   _leaf_html(items, by_id, fill)))

    def top(title, office, extra, items, body):
        return ('<details class="person"><summary><h2>%s</h2>%s'
                '<p class="ptally">%s%s &middot; %s</p></summary>%s</details>'
                % (title, '<p class="office">%s</p>' % office if office else "",
                   _plural(len(items), "statement"), extra, statements_summary(items), body))

    speakers = sorted({s["speaker"] for s in stmts}, key=_speaker_key)
    by_speaker = []
    for name in speakers:
        items = [s for s in stmts if s["speaker"] == name]
        body = "".join(sub(html.escape(t), [s for s in items if topic[s["id"]] == t], True)
                       for t in topic_order(items))
        by_speaker.append(top(_speaker_label(items[0]), html.escape(items[0]["office"]),
                              " &middot; " + _plural(len(topic_order(items)), "topic"), items, body))
    by_topic = []
    for t in topic_order(stmts):
        items = [s for s in stmts if topic[s["id"]] == t]
        names = sorted({s["speaker"] for s in items}, key=_speaker_key)
        body = ""
        for name in names:
            mine = [s for s in items if s["speaker"] == name]
            body += sub(_speaker_label(mine[0]), mine, False)
        by_topic.append(top(html.escape(t), "", " &middot; " + _plural(len(names), "speaker"),
                            items, body))
    return ('<div class="view" id="view-speaker">%s</div>'
            '<div class="view" id="view-topic" hidden>%s</div>'
            % ("".join(by_speaker), "".join(by_topic)))


def render_day(day, back_banner):
    views = _views_html(day)
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
<link rel="alternate" type="application/rss+xml" title="Said &amp; Checked" href="{FEED_PATH}">
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
  details.person {{ border: 0; border-top: 1px solid var(--border); background: none; padding: 0;
                    margin: 0; font-size: 14px; }}
  details.person:last-of-type {{ border-bottom: 1px solid var(--border); }}
  details.person > summary {{ list-style: none; padding: 0.9rem 0 0.9rem 1.4rem; position: relative; }}
  details.person > summary::-webkit-details-marker {{ display: none; }}
  details.person > summary::before {{ content: "+"; position: absolute; left: 0; top: 1.05rem;
                                      color: var(--amber); font-size: 16px; line-height: 1.5; }}
  details.person[open] > summary::before {{ content: "\\2212"; }}
  details.person[open] > summary {{ border-bottom: 1px solid var(--border); margin-bottom: 1.2rem; }}
  details.person[open] {{ padding-bottom: 1.5rem; }}
  details.person .office {{ border: 0; padding: 0; margin: 0; }}
  .ptally {{ color: var(--text); font-size: 12px; margin-top: 0.2rem; }}
  .controls {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
               gap: 0.6rem 1.5rem; margin: 0 0 0.8rem; font-size: 12px; color: var(--text-dim); }}
  .openall, .viewbtn {{ font: inherit; font-size: 12px; color: var(--amber); background: none;
                        border: 0; padding: 0; cursor: pointer; }}
  .viewbtn {{ border: 1px solid var(--border); padding: 2px 10px; margin-left: 0.4rem; }}
  .viewbtn[aria-pressed="true"] {{ color: var(--bg); background: var(--amber);
                                   border-color: var(--amber); }}
  details.sub {{ border: 0; border-left: 1px solid var(--border); background: none;
                 padding: 0 0 0 1rem; margin: 0 0 0.6rem 0.2rem; font-size: 14px; }}
  details.sub > summary {{ padding: 0.35rem 0; }}
  details.sub[open] > summary {{ margin-bottom: 1rem; }}
  details.sub h3 {{ display: inline; font-family: var(--mono); font-weight: 500; font-size: 14px;
                    color: var(--white); }}
  details.sub .ptally {{ color: var(--text-dim); margin: 0 0 0 1rem; }}
  .slot .stmt:last-child {{ border-bottom: 0; }}
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
  details.also {{ margin-top: 0.5rem; font-size: 13px; }}
  details.also summary {{ cursor: pointer; color: var(--text-dim); font-size: 12px; }}
  details.also ul {{ margin: 0.4rem 0 0; padding-left: 1.1rem; }}
  details.also li {{ margin-bottom: 0.35rem; }}
  details.also .where {{ color: var(--text-dim); font-size: 12px; }}
  .counter .where {{ color: var(--text-dim); font-size: 12px; }}
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
  <p class="meta">{subscribe_links()}</p>
  <details>
    <summary>How to read this page</summary>
    <dl>{legend}</dl>
    <p class="rule">Every statement is listed, whatever its kind. There are no scores. Statements
      are grouped two levels deep, by speaker and then topic or by topic and then speaker, and
      every group is collapsed. A topic with a single statement is listed under Other. The counts
      beside a name cover only that person's statements on this page, and are not a rating of
      the person. Statements that could not be checked are
      folded under each speaker.
      Selection: {html.escape(day["selection_rule"])}</p>
  </details>
  <div class="controls">
    <span class="by">Organize by
      <button class="viewbtn" type="button" data-view="speaker" aria-pressed="true">Speaker</button>
      <button class="viewbtn" type="button" data-view="topic" aria-pressed="false">Topic</button>
    </span>
    <button class="openall" type="button" aria-expanded="false">Open all</button>
  </div>
  {views}
</main>
{OPEN_TARGET_SCRIPT}
</body>
</html>
"""


SITE = "https://askamerica.ai"
FEED_FILE = "said-and-checked.xml"
FEED_PATH = "/studies/" + FEED_FILE
# One feed per broad topic, in a directory the build keeps as a standing page.
TOPIC_FEED_DIR = "said-and-checked-feeds"
FEED_DAYS = 14
# The feed leads with these results, most decisive first.
FEED_LEAD_RESULTS = ("false", "contradicted")


def topic_feed_path(topic):
    return "/studies/%s/%s.xml" % (TOPIC_FEED_DIR, topics.slug(topic))


def state_feed_path(code):
    return "/studies/%s/states/%s.xml" % (TOPIC_FEED_DIR, code.lower())


def in_state(s, code):
    """A statement is in a state's feed if its speaker represents the state or it is about it."""
    return s["speaker_state"] == code or code in s["about_states"]


def _reader_links(path, style=""):
    """'RSS · Feedly · Inoreader' for one feed. The reader links add the feed in one click."""
    from urllib.parse import quote
    feed = quote(SITE + path, safe="")
    a = '<a href="%s"%s>%s</a>'
    st = ' style="%s"' % style if style else ""
    return " &middot; ".join([
        a % (path, st, "RSS"),
        a % ("https://feedly.com/i/subscription/feed/" + feed, st, "Feedly"),
        a % ("https://www.inoreader.com/?add_feed=" + feed, st, "Inoreader"),
    ])


def subscribe_links(style=""):
    """'Subscribe: RSS · Feedly · Inoreader · by topic' for the all-statements feed."""
    st = ' style="%s"' % style if style else ""
    return ("Subscribe: " + _reader_links(FEED_PATH, style)
            + ' &middot; <a href="/studies/%s/#topics"%s>by topic</a>' % (SAID_ARCHIVE_SLUG, st)
            + ' &middot; <a href="/studies/%s/#states"%s>by state</a>' % (SAID_ARCHIVE_SLUG, st))


def state_subscribe_rows():
    """One row per state for the all-days page."""
    return ['<li class="study-row">%s<span class="study-date">%s</span></li>'
            % (html.escape(name), _reader_links(state_feed_path(code)))
            for code, name in sorted(US_STATES.items(), key=lambda kv: kv[1])]


def topic_subscribe_rows():
    """One row per broad topic for the all-days page."""
    return ['<li class="study-row">%s<span class="study-date">%s</span></li>'
            % (html.escape(t), _reader_links(topic_feed_path(t))) for t in topics.SAID_TOPICS]


def _feed_title(date, stmts, label=None):
    found = ["%d %s" % (n, RESULTS[r].lower()) for r in FEED_LEAD_RESULTS
             for n in [sum(1 for s in stmts if s.get("result") == r)] if n]
    return "Said & Checked%s, %s: %s" % (
        ", " + label if label else "", date,
        ", ".join(found) if found else "none false or contradicted")


def _feed_description(stmts, page_url):
    """The false and contradicted statements first, then the tally and a link to the day."""
    leads = sorted((s for s in stmts if s.get("result") in FEED_LEAD_RESULTS),
                   key=lambda s: (FEED_LEAD_RESULTS.index(s["result"]), s["id"]))
    parts = []
    if leads:
        items = "".join(
            "<li><strong>%s</strong>, %s: &ldquo;%s&rdquo; <em>%s.</em> %s</li>" % (
                html.escape(s["speaker"]), html.escape(s["office"]),
                html.escape(_excerpt(s["quote"], 40)), RESULTS[s["result"]],
                html.escape(s["finding"]))
            for s in leads)
        parts.append("<p><strong>False or contradicted</strong></p><ul>%s</ul>" % items)
    else:
        parts.append("<p>No statement was found false or contradicted.</p>")
    n, speakers = len(stmts), len({s["speaker"] for s in stmts})
    parts.append("<p>%d statement%s by %d officeholder%s. %s.</p>"
                 % (n, "" if n == 1 else "s", speakers, "" if speakers == 1 else "s",
                    statements_summary(stmts)))
    parts.append('<p><a href="%s">Read every statement and how each was checked</a></p>'
                 % html.escape(page_url, quote=True))
    return "".join(parts)


def feed_xml(days, topic=None, state=None):
    """RSS 2.0 feed of the latest FEED_DAYS days: every statement, one broad topic, or one state
    (postal code). A topic or state feed has an item only for days with a matching statement.
    A day keeps its guid as it is republished during the day, so a reader lists it once."""
    import datetime
    from email.utils import format_datetime
    from xml.sax.saxutils import escape

    _require(topic is None or state is None, "feed_xml", "a feed is by topic or by state, not both")
    if topic is not None:
        label, path, anchor = topic, topic_feed_path(topic), "#topic-" + topics.slug(topic)
        keep = lambda s: s["broad_topic"] == topic
    elif state is not None:
        label, path, anchor = US_STATES[state], state_feed_path(state), "#state-" + state.lower()
        keep = lambda s: in_state(s, state)
    else:
        label, path, anchor = None, FEED_PATH, ""
        keep = lambda s: True
    items = []
    for day in days[:FEED_DAYS]:
        stmts = [s for s in day["statements"] if keep(s)]
        if not stmts:
            continue
        url = "%s/studies/%s/" % (SITE, slug(day))
        y, m, d = (int(p) for p in day["date"].split("-"))
        pub = format_datetime(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc))
        items.append(
            "<item><title>%s</title><link>%s</link><guid isPermaLink=\"false\">%s</guid>"
            "<pubDate>%s</pubDate><description>%s</description></item>"
            % (escape(_feed_title(day["date"], stmts, label)), escape(url), escape(url + anchor),
               pub, escape(_feed_description(stmts, url))))
    title = "Said & Checked" + (": " + label if label else "")
    about = ("What officeholders said each day"
             + (" about " + topic if topic else "")
             + (" from or about " + label if state else "")
             + ", and which statements government data supports, contradicts or rules out.")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        "<title>%s &#8212; AskAmerica</title>"
        "<link>%s/studies/%s/</link>"
        '<atom:link href="%s%s" rel="self" type="application/rss+xml"/>'
        "<description>%s</description>"
        "<language>en-us</language>%s</channel></rss>\n"
        % (escape(title), SITE, SAID_ARCHIVE_SLUG, SITE, escape(path), escape(about),
           "".join(items)))


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
