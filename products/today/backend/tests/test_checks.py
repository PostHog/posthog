import copy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.logic.agent_output import BriefingOutput, problems_with
from products.today.backend.logic.checks import check_content
from products.today.backend.logic.content import BriefingContent
from products.today.backend.logic.fact_sheet import FactSheet

# The stored shapes, as a row in the database holds them.
FACT_SHEET = FactSheet.model_validate(
    {
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
                "facts": {"metric": "Orders", "last_week": "2000", "this_week": "1500", "pct_change": "-25"},
            },
        ],
    }
)

VALID_DATA: dict[str, Any] = {
    "headline": "Two items need your attention",
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
    "labels": {"report:1": "Checkout button hidden on narrow screens", "dashboard:7": "Checkout orders down 25%"},
    "signals": {"report:1": "P2, waits for you", "dashboard:7": "Orders down 25%"},
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
            ("em dash", ["headline"], "One report needs you — today", "dash"),
            ("second highlight", ["paragraphs", 1, 1, "highlight"], True, "may be highlighted"),
            ("unknown item linked", ["paragraphs", 1, 1, "item_key"], "ticket:9", "not in the list"),
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


def _answer(*items: dict[str, Any]) -> BriefingOutput:
    segments = [{"text": "Look at ", "item_key": None, "highlight": False}]
    for index, item in enumerate(items):
        segments.append({"text": item["label"], "item_key": item["key"], "highlight": index == 0})
        segments.append({"text": " and " if index < len(items) - 1 else ".", "item_key": None, "highlight": False})
    return BriefingOutput.model_validate(
        {
            "headline": f"{len(items)} items need you",
            "paragraphs": [segments],
            "items": [
                {
                    "group": "report",
                    "source": "self_driving",
                    "reason": "waiting_for_you",
                    "title": item["label"],
                    "signal": "P2, waits for you",
                    "urgency": 0,
                    "source_product": None,
                    "facts": [],
                    **item,
                }
                for item in items
            ],
        }
    )


class TestProblemsWith(SimpleTestCase):
    @parameterized.expand(
        [
            ("project path", "/project/1/inbox/a", []),
            ("github", "https://github.com/PostHog/posthog/pull/1", []),
            ("another project", "/project/2/inbox/a", ["url of report:a must start with /project/1/"]),
            ("outside site", "https://example.com/login", ["url of report:a must start with /project/1/"]),
            ("javascript", "javascript:alert(1)", ["url of report:a must start with /project/1/"]),
        ]
    )
    def test_an_item_opens_inside_the_project_or_on_github(self, _name: str, url: str, expected: list[str]) -> None:
        problems = problems_with(_answer({"key": "report:a", "label": "report a", "url": url}), team_id=1)

        assert [problem for problem in problems if problem.startswith("url of")] == [
            f"{prefix} or https://github.com/, got {url!r}" for prefix in expected
        ]

    def test_an_item_listed_twice_is_rejected(self) -> None:
        twice = _answer(
            {"key": "report:a", "label": "report a", "url": "/project/1/inbox/a"},
            {"key": "report:a", "label": "report a again", "url": "/project/1/inbox/a"},
        )

        assert "item report:a appears 2 times, expected once" in problems_with(twice, team_id=1)
