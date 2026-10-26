import uuid
from datetime import date
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.facade.contracts import ErrorTrackingIssueBasics
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_sources import rage
from products.today.backend.logic.highlight_types import Context
from products.web_analytics.backend.facade.rage_pages import ErrorsBeforeRage, RagePage

ISSUE_ID = uuid.UUID("01890000-0000-7000-8000-000000000002")
PAGE = RagePage(path="/checkout/…", people=12, clicks=340)
ELEMENT_ITEM = (
    "12 users rage-clicked on /checkout/… in the last 7 days",
    "340 rage clicks · Top element: ‘Pay now’",
    "/replay/home",
)
ERROR_ITEM = (
    "12 users rage-clicked on /checkout/… in the last 7 days",
    "50% of sessions saw the error ‘TypeError: Cannot read properties of undefined’ in the 30 seconds before",
    f"/error_tracking/{ISSUE_ID}",
)


class TestRage(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "an error in half the sessions",
                True,
                PAGE,
                "Pay now",
                ErrorsBeforeRage(6, str(ISSUE_ID), 3),
                True,
                [ERROR_ITEM],
            ),
            (
                "an error in too few sessions",
                True,
                PAGE,
                "Pay now",
                ErrorsBeforeRage(3, str(ISSUE_ID), 2),
                True,
                [ELEMENT_ITEM],
            ),
            (
                "an error in too small a share of sessions",
                True,
                PAGE,
                "Pay now",
                ErrorsBeforeRage(11, str(ISSUE_ID), 3),
                True,
                [ELEMENT_ITEM],
            ),
            (
                "a key that cannot read errors",
                True,
                PAGE,
                "Pay now",
                ErrorsBeforeRage(6, str(ISSUE_ID), 3),
                False,
                [ELEMENT_ITEM],
            ),
            (
                "no element text",
                True,
                PAGE,
                None,
                ErrorsBeforeRage(0, None, 0),
                True,
                [(ELEMENT_ITEM[0], "340 rage clicks", "/replay/home")],
            ),
            ("no page", True, None, None, ErrorsBeforeRage(0, None, 0), True, []),
            (
                "a person who uses none of the rage products",
                False,
                PAGE,
                "Pay now",
                ErrorsBeforeRage(0, None, 0),
                True,
                [],
            ),
        ]
    )
    def test_the_top_rage_page_links_the_error_people_saw_before_they_clicked(
        self,
        _name: str,
        relevant: bool,
        page: RagePage | None,
        element: str | None,
        errors: ErrorsBeforeRage,
        reads_errors: bool,
        expected: list[tuple[str, str, str]],
    ) -> None:
        context = cast(
            Context,
            SimpleNamespace(
                team=SimpleNamespace(id=1),
                user=SimpleNamespace(id=2),
                today=date(2026, 10, 13),
                daily=lambda _name, compute: compute(),
                failures=[],
                allows=lambda *scopes: reads_errors,
                guard=lambda _name, provider, _default: provider(),
            ),
        )
        issue = ErrorTrackingIssueBasics(
            id=ISSUE_ID,
            name="TypeError",
            description="Cannot read properties of undefined",
            status="active",
            severity=None,
            first_seen=None,
        )
        registered = next(s for s in load_sources() if s.name == "rage")

        with (
            patch.object(rage, "uses_product", return_value=relevant),
            patch.object(rage, "find_top_rage_page", return_value=page),
            patch.object(rage, "find_top_rage_element", return_value=element),
            patch.object(rage, "find_errors_before_rage", return_value=errors),
            patch.object(rage, "get_issue_basics", return_value=issue),
        ):
            found = registered.find(context)

        self.assertEqual([(c.title, c.detail, c.url) for c in found.items], expected)
