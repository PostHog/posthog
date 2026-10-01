import copy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.checks import check_content
from products.today.backend.logic.content import BriefingContent
from products.today.backend.logic.fact_sheet import FactSheet

# The stored JSON shapes, as a row in the database holds them.
FACT_SHEET = FactSheet.model_validate(
    {
        "first_name": "Ada",
        "local_day": "2026-09-30",
        "counts": {"items_in_text": 2},
        "failed_sources": [],
        "reason_glossary": {},
        "items": [
            {
                "key": "report:1",
                "group": "report",
                "source": "self_driving",
                "reason": "waiting_for_you",
                "title": "Checkout button is hidden on narrow screens after the last release",
                "url": "/project/1/inbox/1",
                "rank": 1,
                "urgency": 0,
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
                "urgency": 2,
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
                "urgency": 1,
                "in_text": False,
                "top": False,
                "facts": {"ticket_number": 1042, "unread_messages": 6},
            },
        ],
    }
)

VALID_DATA: dict[str, Any] = {
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
VALID = BriefingContent.model_validate(VALID_DATA)


def _with(path: list[Any], value: Any) -> BriefingContent:
    content = copy.deepcopy(VALID_DATA)
    target: Any = content
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return BriefingContent.model_validate(content)


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
                ["labels", "dashboard:7"],
                "The checkout dashboard orders fell a quarter",
                "label for dashboard:7",
            ),
            ("signal missing", ["signals", "dashboard:7"], "", "signal for dashboard:7"),
        ]
    )
    def test_broken_rule_is_reported(self, _name: str, path: list[Any], value: Any, expected: str) -> None:
        problems = check_content(FACT_SHEET, _with(path, value))

        assert any(expected in problem for problem in problems), problems

    def test_the_number_check_can_be_left_to_the_writer(self) -> None:
        content = _with(["paragraphs", 1, 2, "text"], " fell 41% this week.")

        assert check_content(FACT_SHEET, content, check_numbers=False) == []
