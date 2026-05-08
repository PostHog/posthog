"""Unit tests for mcp_server helpers — no Playwright, no MCP transport."""

import pytest

import mcp_server

import cli


def _visit(visit_number: int, events: list[str], error: str | None = None) -> cli.VisitResult:
    requests = (
        [
            cli.AnalyticsRequest(
                timestamp="t", url="https://us.i.posthog.com/i/v0/e/", method="POST", status=200, events=events
            )
        ]
        if events
        else []
    )
    return cli.VisitResult(
        visit_number=visit_number,
        scenario="new-user",
        url="https://example.com",
        timestamp="t",
        posthog_requests=requests,
        error=error,
    )


class TestSummarizeVisitsVerified:
    @pytest.mark.parametrize(
        "results,expected_verified,expected_pageviews",
        [
            ([], False, 0),
            ([_visit(1, ["$pageview"])], True, 1),
            ([_visit(1, ["$pageview"]), _visit(2, ["$pageview"])], True, 2),
            # Only one of three visits captured a pageview — must NOT be verified.
            ([_visit(1, ["$pageview"]), _visit(2, []), _visit(3, [])], False, 1),
            # Pageview present but a sibling visit errored — not verified.
            ([_visit(1, ["$pageview"]), _visit(2, ["$pageview"], error="boom")], False, 2),
            # Non-pageview events alone don't satisfy verified.
            ([_visit(1, ["$autocapture"])], False, 0),
        ],
    )
    def test_verified_requires_pageview_per_visit(self, results, expected_verified, expected_pageviews):
        summary = mcp_server._summarize_visits(results)
        assert summary["verified"] is expected_verified
        assert summary["pageviews"] == expected_pageviews
        assert summary["total_visits"] == len(results)
