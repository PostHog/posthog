from typing import Any

from posthog.test.base import APIBaseTest

from rest_framework import status

from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    REVIEWS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.engineering_analytics.backend.tests._github_fixtures import _pr_row
from products.engineering_analytics.backend.tests._logic_helpers import _ago, _WarehouseMixin

_AGENT_CONTEXT_BODY = "## Problem\n\n- None.\n\n## 🤖 Agent context\n\n**Agent:** Claude Code, Fable 5.2\n"
_UNFILLED_TEMPLATE_BODY = "## Problem\n\n- None.\n\n## 🤖 Agent context\n\n**Agent:** tool, model\n"


def _merged(number: int, login: str, *, merged_days_ago: int = 5, **overrides: Any) -> dict[str, Any]:
    return _pr_row(number, login, "closed", 0, _ago(10), merged_at=_ago(merged_days_ago), **overrides)


def _review(review_id: int, pr_number: int, login: str, state: str, submitted_at: str) -> dict[str, Any]:
    return {
        "id": review_id,
        "pr_number": pr_number,
        "user": f'{{"login": "{login}"}}',
        "state": state,
        "commit_id": "",
        "submitted_at": submitted_at,
    }


def _counts(entries: list[dict[str, Any]], key: str) -> dict[str, tuple[int, int]]:
    return {entry[key]: (entry["merged_pr_count"], entry["reverted_pr_count"]) for entry in entries}


class TestRevertOutcomes(_WarehouseMixin, APIBaseTest):
    def _get(self) -> dict[str, Any]:
        response = self.client.get(f"/api/projects/{self.team.id}/engineering_analytics/revert_outcomes/")
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    def test_links_reverts_to_merged_pull_requests_by_cohort(self) -> None:
        self._create_table(
            "github_pull_requests",
            PULL_REQUESTS_COLUMNS,
            [
                _merged(100, "alice", body=_AGENT_CONTEXT_BODY),
                _merged(101, "alice", body=_AGENT_CONTEXT_BODY),
                _merged(102, "bob", body=_UNFILLED_TEMPLATE_BODY),
                _merged(103, "bob"),
                _merged(104, "dependabot[bot]"),
                _merged(105, "carol", body="Follow-up to the cache change. Reverts #101 in spirit only."),
                _merged(106, "erin", body="Quoting the template:\n\n> **Agent:** Claude Code, Fable 5.2\n"),
                _merged(
                    110,
                    "alice",
                    merged_days_ago=2,
                    title='Revert "PR 100 (#100)"',
                    body="Reverts PostHog/posthog#100",
                ),
                _merged(
                    111,
                    "bob",
                    merged_days_ago=1,
                    title="revert: PR 102",
                    body="No longer reverts #103\nThis reverts #102.\n\nBroke the gate.",
                ),
                _merged(112, "bob", merged_days_ago=1, title='Revert "PR 103"', body="Reverts other-org/other#103"),
                _merged(107, "bob", merged_days_ago=4),
                _merged(113, "carol", merged_days_ago=6, title='Revert "PR 99"', body="Reverts #107"),
                _merged(114, "carol", merged_days_ago=3, title='Revert "PR 107"', body="Reverts #107"),
            ],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])
        self._create_table(
            "github_reviews",
            REVIEWS_COLUMNS,
            [
                _review(1, 100, "stamphog[bot]", "APPROVED", _ago(6)),
                _review(2, 101, "dana", "approved", _ago(6)),
                _review(3, 102, "stamphog[bot]", "APPROVED", _ago(6)),
                _review(4, 102, "dana", "APPROVED", _ago(6)),
                _review(5, 104, "dana", "CHANGES_REQUESTED", _ago(6)),
                _review(6, 104, "dana", "APPROVED", _ago(3)),
                _review(7, 105, "dana", "APPROVED", _ago(6)),
            ],
        )

        outcomes = self._get()

        assert (outcomes["merged_pr_count"], outcomes["reverted_pr_count"]) == (8, 3)
        assert outcomes["reverted_share"] == 3 / 8
        assert _counts(outcomes["by_authorship"], "authorship") == {
            "bot": (1, 0),
            "agent_context": (2, 1),
            "no_agent_context": (5, 2),
        }
        assert _counts(outcomes["by_approval"], "approval") == {
            "human": (3, 1),
            "automated_only": (1, 1),
            "none": (4, 1),
        }
        assert [
            (pr["number"], pr["reverting_pr_number"], pr["authorship"], pr["approval"], pr["merge_to_revert_seconds"])
            for pr in outcomes["reverted_pull_requests"]
        ] == [
            (102, 111, "no_agent_context", "human", 4 * 86400),
            (100, 110, "agent_context", "automated_only", 3 * 86400),
            (107, 114, "no_agent_context", "none", 1 * 86400),
        ]
        assert outcomes["truncated"] is False

    def test_reports_missing_body_and_review_data_instead_of_zero_reverts(self) -> None:
        columns_without_body = {name: column for name, column in PULL_REQUESTS_COLUMNS.items() if name != "body"}
        self._create_table(
            "github_pull_requests",
            columns_without_body,
            [_merged(100, "alice"), _merged(110, "alice", merged_days_ago=2, title='Revert "PR 100 (#100)"')],
        )
        self._create_table("github_workflow_runs", WORKFLOW_RUNS_COLUMNS, [])

        outcomes = self._get()

        assert outcomes["body_data_available"] is False
        assert outcomes["review_data_available"] is False
        assert outcomes["merged_pr_count"] == 1
        assert outcomes["reverted_pr_count"] is None
        assert outcomes["by_authorship"] == []
        assert outcomes["reverted_pull_requests"] == []
