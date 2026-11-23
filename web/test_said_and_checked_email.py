"""The daily email ends with how the checks are made; the RSS feed items do not carry it."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import said_and_checked as sc  # noqa: E402


def _day():
    stmt = {"id": "1", "speaker": "A. Senator", "office": "U.S. Senator", "quote": "Prices rose.",
            "kind": "factual", "result": "supported", "finding": "CPI rose 3.0%.",
            "broad_topic": "Economy"}
    return {"date": "2026-11-23", "statements": [stmt]}


def test_email_ends_with_how_checked_block():
    body = sc.email_html(_day())
    assert body.endswith(sc.EMAIL_HOW_CHECKED + "</div>")
    assert "How these checks are made." in body
    assert 'href="https://askamerica.ai/#download"' in body
    for client in ("MCP", "Python", "Java", "Node", "DBeaver"):
        assert client in sc.EMAIL_HOW_CHECKED


def test_feed_description_has_no_how_checked_block():
    day = _day()
    desc = sc._feed_description(day["statements"], "https://askamerica.ai/studies/x/",
                                "https://askamerica.ai/x.png", "alt")
    assert "How these checks are made." not in desc
