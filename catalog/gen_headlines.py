#!/usr/bin/env python3
"""Generate the "Ripped from Today's Headlines" MkDocs pages from the askamerica-news-check
skill's output (news-check-results/ in the calcite repo).

Reads NEWS_CORPUS/.checked-topics.json (one entry per checked story: topic_slug, headline,
checked_date, run_subpath, verdict, source_url) plus each story's saved persona answers under
NEWS_CORPUS/<run_subpath's qN>/<persona>/<date>/agent.md, and writes:
  - docs/headlines/index.md         "Ripped from Today's Headlines" -- the most recent day's
                                     stories, prominent
  - docs/headlines/archive.md       every earlier day, most recent first
  - docs/headlines/<topic_slug>.md  one page per story, every persona's answer that ran

Called from gen_docs.py's main(); `nav_entries()` supplies the mkdocs nav block. Both calls are
wrapped defensively there -- this module raising or NEWS_CORPUS being absent skips the headlines
section for that build rather than failing the whole site.

Run:  NEWS_CORPUS=/path/to/calcite/news-check-results \
      <venv>/bin/python catalog/gen_headlines.py
"""
import json
import os
import re

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.environ.get(
    "NEWS_CORPUS",
    "/home/kstott/calcite/news-check-results",
)
DOCS = os.path.join(HERE, "docs")
HEADLINES = os.path.join(DOCS, "headlines")

MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])

VERDICT_LABEL = {
    "confirmed": ("✅", "Confirmed"),
    "contradicted": ("❌", "Contradicted"),
    "partial": ("⚠️", "Partially supported"),
    "not-checkable": ("❔", "Not checkable here"),
}

PERSONA_ORDER = ["everyman", "askamerica", "expert"]
PERSONA_LABEL = {
    "everyman": "Everyman (no connector)",
    "askamerica": "AskAmerica",
    "expert": "Expert (fully-equipped analyst)",
}


def render(md_text):
    MD.reset()
    return MD.convert(md_text)


def load_history():
    """The .checked-topics.json array, oldest first as written, grouped by checked_date."""
    path = os.path.join(CORPUS, ".checked-topics.json")
    if not os.path.isfile(path):
        return []
    with open(path) as fh:
        return json.load(fh)


def qdir_for(run_subpath):
    """'q3/askamerica/2026-09-26' -> ('q3', 'askamerica', '2026-09-26')."""
    parts = run_subpath.strip("/").split("/")
    if len(parts) != 3:
        return None
    return tuple(parts)


def persona_answer(qid, persona, date):
    """The saved agent.md for one persona of one story, or None if that persona didn't run
    (most entries so far are askamerica-only; the daily 3-persona job adds the other two)."""
    path = os.path.join(CORPUS, qid, persona, date, "agent.md")
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        text = fh.read()
    # Drop a leading H1 -- the story page supplies its own title.
    return re.sub(r"\A#\s+[^\n]*\n", "", text).strip()


def story_page(entry):
    qid, _persona0, date = qdir_for(entry["run_subpath"]) or (None, None, None)
    L = [f"# {entry['headline']}", ""]

    icon, label = VERDICT_LABEL.get(entry.get("verdict", ""), ("❔", entry.get("verdict", "unknown")))
    L += [f"**Verdict:** {icon} {label}  ", f"**Checked:** {entry['checked_date']}  "]
    if entry.get("source_url"):
        L += [f"**Source:** [{entry['source_url']}]({entry['source_url']})"]
    L += [""]

    if qid is None:
        L += ["!!! bug \"Malformed run_subpath\"", "", f"    `{entry.get('run_subpath')}`", ""]
        return "\n".join(L) + "\n"

    found_any = False
    for persona in PERSONA_ORDER:
        body = persona_answer(qid, persona, date)
        if body is None:
            continue
        found_any = True
        L += [f"## {PERSONA_LABEL[persona]}", "", body, ""]

    if not found_any:
        # Single-persona runs (the ad-hoc askamerica-only mode) still have SOMETHING saved
        # under the run_subpath's own persona directory even if it's not in PERSONA_ORDER's
        # exact casing/shape -- fall back to whatever's there before giving up.
        base = os.path.join(CORPUS, qid)
        if os.path.isdir(base):
            for persona in sorted(os.listdir(base)):
                body = persona_answer(qid, persona, date)
                if body is not None:
                    L += [f"## {PERSONA_LABEL.get(persona, persona)}", "", body, ""]
                    found_any = True
    if not found_any:
        L += ["!!! warning \"No saved answer found\"", "",
              f"    Expected under `{qid}/<persona>/{date}/agent.md`.", ""]

    return "\n".join(L) + "\n"


def index_page(by_date, dates_sorted):
    today = dates_sorted[0] if dates_sorted else None
    L = [
        "# Ripped from Today's Headlines",
        "",
        "AskAmerica checks real, current news claims directly against primary government data —",
        "no synthetic questions, no pre-written answer key. Every story below was found and",
        "verified the same day it ran.",
        "",
    ]
    if today is None:
        L += ["_No stories checked yet._", ""]
        open(os.path.join(HEADLINES, "index.md"), "w").write("\n".join(L) + "\n")
        return

    L += [f"## {today}", ""]
    for entry in by_date[today]:
        icon, label = VERDICT_LABEL.get(entry.get("verdict", ""), ("❔", entry.get("verdict", "")))
        L.append(f"- {icon} **[{entry['headline']}]({entry['topic_slug']}.md)** — {label}")
    L += [""]

    if len(dates_sorted) > 1:
        L += ["Older stories have rotated into the [archive](archive.md).", ""]

    open(os.path.join(HEADLINES, "index.md"), "w").write("\n".join(L) + "\n")


def archive_page(by_date, dates_sorted):
    L = ["# Headlines archive", "", "Every previously-checked story, most recent first.", ""]
    for date in dates_sorted[1:]:
        L += [f"## {date}", ""]
        for entry in by_date[date]:
            icon, label = VERDICT_LABEL.get(entry.get("verdict", ""), ("❔", entry.get("verdict", "")))
            L.append(f"- {icon} **[{entry['headline']}]({entry['topic_slug']}.md)** — {label}")
        L += [""]
    if len(dates_sorted) <= 1:
        L += ["_Nothing archived yet — check back after the next day's run._", ""]
    open(os.path.join(HEADLINES, "archive.md"), "w").write("\n".join(L) + "\n")


def nav_entries():
    history = load_history()
    nav = ["  - Headlines:", "      - Ripped from Today's Headlines: headlines/index.md",
           "      - Archive: headlines/archive.md"]
    seen = set()
    for entry in sorted(history, key=lambda e: e["checked_date"], reverse=True):
        slug = entry["topic_slug"]
        if slug in seen:
            continue
        seen.add(slug)
        nav.append(f"      - '{entry['headline'][:60]}': headlines/{slug}.md")
    return nav


def main():
    os.makedirs(HEADLINES, exist_ok=True)
    history = load_history()
    by_date = {}
    seen_slugs = {}
    for entry in history:
        # A slug re-checked on a later date supersedes the earlier entry on its own page,
        # but each date's index/archive listing shows the entry as it was checked that day.
        by_date.setdefault(entry["checked_date"], []).append(entry)
        seen_slugs[entry["topic_slug"]] = entry  # last-checked-date wins for the story page
    dates_sorted = sorted(by_date, reverse=True)

    for entry in seen_slugs.values():
        open(os.path.join(HEADLINES, f"{entry['topic_slug']}.md"), "w").write(story_page(entry))

    index_page(by_date, dates_sorted)
    archive_page(by_date, dates_sorted)
    print(f"generated: {len(seen_slugs)} headline pages across {len(dates_sorted)} day(s)")


if __name__ == "__main__":
    main()
