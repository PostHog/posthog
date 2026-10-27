import re
import json
import uuid
from datetime import date
from types import SimpleNamespace
from typing import cast
from urllib.parse import parse_qs, urlparse

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
REPLAY_URL = (
    "/replay/home?filters=%7B%22date_from%22%3A%22-7d%22%2C%22filter_group%22%3A%7B%22type%22%3A%22AND%22%2C"
    "%22values%22%3A%5B%7B%22type%22%3A%22AND%22%2C%22values%22%3A%5B%7B%22id%22%3A%22%24rageclick%22%2C"
    "%22name%22%3A%22%24rageclick%22%2C%22type%22%3A%22events%22%2C%22properties%22%3A%5B%7B%22key%22%3A"
    "%22%24pathname%22%2C%22type%22%3A%22event%22%2C%22operator%22%3A%22regex%22%2C%22value%22%3A%22%5E%2F"
    "checkout%2F%28%3F%3A%5B0-9a-f-%5D%7B8%2C%7D%7C%5B0-9%5D%2B%29%24%22%7D%5D%7D%5D%7D%5D%7D%7D"
)
ELEMENT_ITEM = (
    "12 users rage-clicked on /checkout/… in the last 7 days",
    "340 rage clicks · Top element: ‘Pay now’",
    REPLAY_URL,
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
                [(ELEMENT_ITEM[0], "340 rage clicks", REPLAY_URL)],
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

    @parameterized.expand(
        [
            ("/checkout/…", "/checkout/12345", True),
            ("/checkout/…", "/checkout/0189abcd-0000-7000", True),
            ("/checkout/…", "/checkout", False),
            ("/checkout/…/pay", "/checkout/42/pay", True),
            ("/checkout/…/pay", "/checkout/42/payment", False),
            ("/a.b", "/axb", False),
        ]
    )
    def test_the_replay_link_filters_rage_clicks_on_the_reported_page(
        self, path: str, pathname: str, matches: bool
    ) -> None:
        filters = json.loads(parse_qs(urlparse(rage._replay_url(path)).query)["filters"][0])
        (rage_click,) = filters["filter_group"]["values"][0]["values"]
        (page_filter,) = rage_click["properties"]

        self.assertEqual((rage_click["id"], filters["date_from"]), ("$rageclick", "-7d"))
        self.assertEqual(bool(re.search(page_filter["value"], pathname)), matches)
