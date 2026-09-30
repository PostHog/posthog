import copy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.checks import check_content
from products.today.backend.logic.draft import build_draft

FACT_SHEET: dict[str, Any] = {
    "first_name": "Ada",
    "local_day": "2026-09-30",
    "counts": {"reports_in_text": 1, "more_reports_for_you": 12},
    "failed_sources": [],
    "items": [
        {
            "key": "report:1",
            "group": "report",
            "source": "self_driving",
            "reason": "waiting_for_you",
            "title": "Checkout button is hidden on narrow screens after the last release",
            "url": "/project/1/inbox/1",
            "rank": 1,
            "in_text": True,
            "top": True,
            "facts": {"priority": "P2", "status": "pending_input"},
        },
        {
            "key": "dashboard:7",
            "group": "dashboard",
            "source": "product_analytics",
            "reason": "dashboard_you_viewed",
            "title": "Checkout",
            "url": "/project/1/dashboard/7",
            "rank": 2,
            "in_text": True,
            "top": False,
            "facts": {"metric": "Orders", "last_week": 2000, "this_week": 1500, "pct_change": -25.0},
        },
        {
            "key": "ticket:9",
            "group": "other",
            "source": "support",
            "reason": "assigned_ticket",
            "title": "Support ticket #1042",
            "url": "/project/1/support/tickets/9",
            "rank": 3,
            "in_text": False,
            "top": False,
            "facts": {"ticket_number": 1042, "unread_messages": 6},
        },
    ],
}

VALID: dict[str, Any] = {
    "headline": "One report needs your input.",
    "paragraphs": [
        [
            {"text": "A ", "item_key": None, "highlight": False},
            {"text": "checkout button is hidden on narrow screens", "item_key": "report:1", "highlight": True},
            {"text": " since the last release.", "item_key": None, "highlight": False},
        ],
        [
            {"text": "Orders on ", "item_key": None, "highlight": False},
            {"text": "the checkout dashboard", "item_key": "dashboard:7", "highlight": False},
            {"text": " fell 25%, from $2,000 to $1,500.", "item_key": None, "highlight": False},
        ],
    ],
    "labels": {
        "report:1": "Checkout button hidden on narrow screens",
        "dashboard:7": "Checkout orders down 25%",
        "ticket:9": "Ticket #1042",
    },
    "signals": {"report:1": "P2, waits for you", "dashboard:7": "Orders down 25%", "ticket:9": "6 unread messages"},
}


def _with(path: list[Any], value: Any) -> dict[str, Any]:
    content = copy.deepcopy(VALID)
    target: Any = content
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return content


class TestCheckContent(SimpleTestCase):
    def test_valid_output_passes(self) -> None:
        assert check_content(FACT_SHEET, VALID) == []

    @parameterized.expand(
        [
            ("invented number", ["paragraphs", 1, 2, "text"], " fell 41% this week.", "number 41"),
            ("em dash", ["headline"], "One report needs you — today", "dash"),
            ("second highlight", ["paragraphs", 1, 1, "highlight"], True, "may be highlighted"),
            ("item outside the text linked", ["paragraphs", 1, 1, "item_key"], "ticket:9", "not in the text"),
            (
                "link starts with punctuation",
                ["paragraphs", 0, 1, "text"],
                ", the checkout button",
                "does not start with a word",
            ),
            (
                "label too long",
                ["labels", "ticket:9"],
                "A support ticket that waits for your reply",
                "label for ticket:9",
            ),
            ("signal missing", ["signals", "dashboard:7"], "", "signal for dashboard:7"),
        ]
    )
    def test_broken_rule_is_reported(self, _name: str, path: list[Any], value: Any, expected: str) -> None:
        problems = check_content(FACT_SHEET, _with(path, value))

        assert any(expected in problem for problem in problems), problems

    def test_draft_links_every_text_item_once_and_highlights_the_top_item(self) -> None:
        draft = build_draft(FACT_SHEET)

        problems = check_content(FACT_SHEET, draft)

        # The draft keeps the source titles, so only the link-length rule may fail on it.
        assert [problem for problem in problems if "more than 8 words" not in problem] == []
        assert set(draft["labels"]) == {"report:1", "dashboard:7", "ticket:9"}
