#!/usr/bin/env python3
"""Generate the public "Studies" page for the main askamerica.ai site.

Reads the question bank (questions.yaml) from the askamerica-comparative-eval
skill in a calcite checkout, and for every question, finds the MOST RECENT
`askamerica`-persona run's published report and republishes it under this
site at /studies/<qid>/. Only the askamerica persona is surfaced here — the
other three personas (everyman/professional/expert) are internal comparison
arms, not public content.

Writes:
  web/studies.html          categorized index, one row per question in the bank
  web/studies/<qid>/index.html   that question's most recent askamerica report

Run (from the web/ directory, or anywhere with --corpus/--out set):
  EVAL_CORPUS=/path/to/calcite/.claude/skills/askamerica-comparative-eval \
      python3 build_studies.py

Then `./deploy.sh` as usual — deploy.sh rsyncs the whole web/ tree (minus
secrets/tooling), so studies.html and studies/ ship with everything else.
Re-run this script before every deploy; it is not wired into deploy.sh
automatically, the same manual-build convention the catalog/ site uses.
"""
import html
import os
import re
import shutil
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))

CORPUS = os.environ.get(
    "EVAL_CORPUS",
    os.path.join(HERE, "..", "..", "calcite", ".claude", "skills", "askamerica-comparative-eval"),
)
CORPUS = os.path.abspath(CORPUS)

# Mirrors compose_prompt.py's own PROJECT_ROOT/RESULTS_ROOT derivation exactly:
# CORPUS is .../<repo>/.claude/skills/askamerica-comparative-eval, so three
# dirname() calls up from CORPUS reaches the repo root. This has to match that
# script's logic bit-for-bit, since the q<N> directory names below depend on it.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(CORPUS)))
RESULTS_ROOT = os.path.join(REPO_ROOT, "comparative-test-results")

OUT = os.path.join(HERE, "studies")

BACK_BANNER = """
<div style="position:sticky;top:0;z-index:999;background:#080b0f;border-bottom:1px solid #1e2d3d;
padding:10px 20px;font-family:'JetBrains Mono',monospace;font-size:13px;">
  <a href="/studies/" style="color:#e8a24a;text-decoration:none;">&larr; All studies</a>
  <span style="color:#768390;"> &middot; </span>
  <a href="/" style="color:#768390;text-decoration:none;">askamerica.ai</a>
</div>
""".strip()


def load_bank():
    path = os.path.join(CORPUS, "questions.yaml")
    with open(path) as fh:
        bank = yaml.safe_load(fh)
    for q in bank:
        if not (q.get("plain_question") or "").strip():
            sys.exit("question %r has no plain_question" % q["id"])
    return bank


ANSWER_FILES = ("report.html", "agent-report.html", "agent.html", "agent-report-1.html", "agent.md")


def _has_content(run_dir):
    """A run directory counts as a real answer only if it holds one of the
    known answer-bearing files. A directory with only prompt.md (or nothing)
    means the run started but never delivered — the harness's most common
    failure mode — and should not be surfaced as "the" answer just because
    it is the most recent date on disk."""
    return any(os.path.isfile(os.path.join(run_dir, name)) for name in ANSWER_FILES)


def latest_askamerica_run(n):
    """The most recent (by ISO date, lexical sort = chronological) askamerica
    run directory for bank position n that actually delivered an answer, or
    None if askamerica has never run on this question yet (or every run on
    it failed to deliver)."""
    persona_dir = os.path.join(RESULTS_ROOT, "q%d" % n, "askamerica")
    if not os.path.isdir(persona_dir):
        return None
    dates = sorted(
        d for d in os.listdir(persona_dir)
        if os.path.isdir(os.path.join(persona_dir, d)) and re.match(r"\d{4}-\d{2}-\d{2}", d)
    )
    for d in reversed(dates):
        run_dir = os.path.join(persona_dir, d)
        if _has_content(run_dir):
            return run_dir, d
    return None


def render_question_page(qid, plain_question, run_dir, run_date):
    """Write web/studies/<qid>/index.html from that run's report.html (preferred)
    or agent.md (fallback, escaped into a <pre> block — no markdown renderer is
    pulled in for one rarely-hit path).

    The self-contained HTML report's filename has varied across the harness's
    history — `report.html` is current (server-side `publish_report`), but many
    runs predate that and carry `agent-report.html`, `agent.html`, or (rarely)
    `agent-report-1.html` instead. Try all of them, in the order a run is most
    likely to have used, before falling back to the plain-text agent.md render."""
    dest_dir = os.path.join(OUT, qid)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "index.html")

    for candidate in ("report.html", "agent-report.html", "agent.html", "agent-report-1.html"):
        report = os.path.join(run_dir, candidate)
        if os.path.isfile(report):
            with open(report) as fh:
                body = fh.read()
            # The report is self-contained (own <title>/<style>/inline SVGs) — just
            # splice a small back-link banner in right after <body>, rather than
            # trying to merge it into this site's own nav/CSS and risking collisions.
            body = re.sub(r"(<body[^>]*>)", r"\1\n" + BACK_BANNER, body, count=1)
            with open(dest, "w") as fh:
                fh.write(body)
            return

    agent_md = os.path.join(run_dir, "agent.md")
    if os.path.isfile(agent_md):
        with open(agent_md) as fh:
            text = fh.read()
        with open(dest, "w") as fh:
            fh.write(_fallback_page(plain_question, run_date, text))
        return

    with open(dest, "w") as fh:
        fh.write(_fallback_page(plain_question, run_date, "(no answer text found)"))


def _fallback_page(plain_question, run_date, text):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(plain_question)}</title>
<style>
  body {{ background:#080b0f; color:#cdd9e5; font-family:'JetBrains Mono',monospace;
          font-size:14px; line-height:1.7; margin:0; }}
  main {{ max-width:800px; margin:0 auto; padding:2rem; }}
  h1 {{ color:#f0f6fc; font-size:1.3rem; }}
  pre {{ white-space:pre-wrap; word-wrap:break-word; }}
</style></head>
<body>
{BACK_BANNER}
<main>
<h1>{html.escape(plain_question)}</h1>
<p style="color:#768390;">askamerica run &middot; {html.escape(run_date)}</p>
<pre>{html.escape(text)}</pre>
</main>
</body></html>
"""


def build_index(bank, entries):
    """web/studies.html — categorized list, plain_question text linking to
    /studies/<qid>/ when a run exists, shown unlinked (greyed) otherwise."""
    by_category = {}
    for q, entry in zip(bank, entries):
        by_category.setdefault(q.get("category", "uncategorized"), []).append((q, entry))

    cards = []
    for cat in sorted(by_category):
        rows = []
        for q, entry in sorted(by_category[cat], key=lambda pair: pair[0]["plain_question"]):
            plain = html.escape(q["plain_question"])
            if entry:
                _, run_date = entry
                rows.append(
                    f'<li class="study-row"><a href="/studies/{q["id"]}/">{plain}</a>'
                    f'<span class="study-date">answered {html.escape(run_date)}</span></li>'
                )
            else:
                rows.append(
                    f'<li class="study-row study-pending">{plain}'
                    f'<span class="study-date">not yet answered</span></li>'
                )
        label = cat.replace("-", " ")
        cards.append(
            f'<div class="study-cat"><h2>{html.escape(label)}</h2><ul>{"".join(rows)}</ul></div>'
        )

    answered = sum(1 for _, e in zip(bank, entries) if e)
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Studies — AskAmerica</title>
<meta name="description" content="Every question in the AskAmerica comparative-eval bank, answered directly against federal data. Browse by topic; every answer traces to a primary government source.">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#1a3a8a">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #080b0f; --bg2: #0d1117; --bg3: #111820; --border: #1e2d3d;
    --amber: #e8a24a; --amber-dim: #7a5120; --amber-glow: rgba(232,162,74,0.12);
    --text: #cdd9e5; --text-dim: #768390; --white: #f0f6fc;
    --mono: 'JetBrains Mono', monospace; --serif: 'Instrument Serif', serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: var(--mono);
          font-size: 14px; line-height: 1.7; }}
  nav {{ position: sticky; top: 0; z-index: 100; display: flex; align-items: center;
         justify-content: space-between; padding: 0 2rem; height: 56px;
         background: rgba(8,11,15,0.9); backdrop-filter: blur(12px);
         border-bottom: 1px solid var(--border); }}
  .nav-logo {{ display: flex; align-items: center; gap: 10px; text-decoration: none;
               color: var(--white); font-weight: 700; font-size: 15px; }}
  .nav-links {{ display: flex; gap: 1.75rem; list-style: none; }}
  .nav-links a {{ color: var(--text-dim); text-decoration: none; font-size: 13px; }}
  .nav-links a:hover {{ color: var(--white); }}
  main {{ max-width: 900px; margin: 0 auto; padding: 4rem 2rem 6rem; }}
  .hero-label {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase;
                 color: var(--amber); margin-bottom: 1rem; }}
  h1 {{ font-family: var(--serif); font-size: clamp(1.8rem, 4vw, 2.6rem); font-weight: 400;
        color: var(--white); margin-bottom: 1rem; }}
  .hero-sub {{ color: var(--text-dim); max-width: 560px; font-size: 14px; margin-bottom: 1.5rem; }}
  .hero-count {{ color: var(--text-dim); font-size: 12px; margin-bottom: 3rem; }}
  .study-cat {{ margin-bottom: 2.5rem; }}
  .study-cat h2 {{ font-size: 13px; letter-spacing: 0.06em; text-transform: uppercase;
                   color: var(--amber); border-bottom: 1px solid var(--border);
                   padding-bottom: 0.6rem; margin-bottom: 0.8rem; }}
  .study-cat ul {{ list-style: none; }}
  .study-row {{ display: flex; justify-content: space-between; align-items: baseline;
                gap: 1rem; padding: 0.7rem 0; border-bottom: 1px solid var(--border); }}
  .study-row a {{ color: var(--text); text-decoration: none; font-size: 14px; line-height: 1.5; }}
  .study-row a:hover {{ color: var(--amber); }}
  .study-pending {{ color: var(--text-dim); font-style: italic; }}
  .study-date {{ color: var(--text-dim); font-size: 11px; white-space: nowrap; flex-shrink: 0; }}
</style>
</head>
<body>
<nav>
  <a href="/" class="nav-logo">
    <img class="nav-logo-mark" src="/icon.svg" width="28" height="28" alt="AskAmerica">
    AskAmerica
  </a>
  <ul class="nav-links">
    <li><a href="/#datasets">Datasets</a></li>
    <li><a href="/catalog/">Catalog</a></li>
    <li><a href="/studies/">Studies</a></li>
    <li><a href="/#pricing">Pricing</a></li>
  </ul>
</nav>
<main>
  <div class="hero-label">Studies</div>
  <h1>Questions people actually ask, answered against federal data</h1>
  <p class="hero-sub">Every question below is run directly through AskAmerica against primary
    government sources — every number traces back to the table and query that produced it.</p>
  <p class="hero-count">{answered} of {len(bank)} questions answered so far</p>
  {"".join(cards)}
</main>
</body>
</html>
"""
    with open(os.path.join(HERE, "studies.html"), "w") as fh:
        fh.write(page)


def main():
    bank = load_bank()
    os.makedirs(OUT, exist_ok=True)
    entries = []
    for n, q in enumerate(bank, 1):
        found = latest_askamerica_run(n)
        if found:
            run_dir, run_date = found
            render_question_page(q["id"], q["plain_question"], run_dir, run_date)
        entries.append(found)

    # Remove any studies/<qid>/ left over from a question that no longer has a
    # delivered run (or was renamed/retired) — a prior build's stale page must
    # not survive into this one just because nothing overwrote it.
    live_qids = {q["id"] for q, e in zip(bank, entries) if e}
    for qid in os.listdir(OUT):
        if qid not in live_qids and os.path.isdir(os.path.join(OUT, qid)):
            shutil.rmtree(os.path.join(OUT, qid))

    build_index(bank, entries)
    answered = sum(1 for e in entries if e)
    print(f"generated: studies.html + {answered} question pages ({len(bank)} in bank)")


if __name__ == "__main__":
    main()
