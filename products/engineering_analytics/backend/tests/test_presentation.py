from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest import mock

from rest_framework import status

from products.engineering_analytics.backend.facade import contracts

_VIEWS = "products.engineering_analytics.backend.presentation.views.api"


def _pr_lifecycle() -> contracts.PRLifecycle:
    return contracts.PRLifecycle(
        pull_request=contracts.PullRequest(
            id=1010,
            number=10,
            title="PR 10",
            author=contracts.Author(handle="alice", display_name="alice", avatar_url="https://x", is_bot=False),
            repo=contracts.RepoRef(provider="github", owner="PostHog", name="posthog"),
            state=contracts.PRState.MERGED,
            is_draft=False,
            created_at=datetime(2026, 1, 10, tzinfo=UTC),
            merged_at=datetime(2026, 1, 12, tzinfo=UTC),
            closed_at=datetime(2026, 1, 12, tzinfo=UTC),
        ),
        events=[
            contracts.PRLifecycleEvent(kind=contracts.PRLifecycleEventKind.OPENED, at=datetime(2026, 1, 10, tzinfo=UTC))
        ],
    )


def _cards() -> contracts.CICardSummary:
    return contracts.CICardSummary(open_prs=5, repos=2, stuck=1, failing_ci=1)


def _pr_list_item() -> contracts.PullRequestListItem:
    return contracts.PullRequestListItem(
        number=10,
        title="PR 10",
        author=contracts.Author(handle="alice", display_name="alice", avatar_url="https://x", is_bot=False),
        repo=contracts.RepoRef(provider="github", owner="PostHog", name="posthog"),
        state=contracts.PRState.OPEN,
        is_draft=False,
        created_at=datetime(2026, 1, 10, tzinfo=UTC),
        merged_at=None,
        open_to_merge_seconds=None,
        labels=["bug"],
        ci=contracts.CIStatusRollup(runs=3, passing=2, failing=1, pending=0),
    )


def _workflow_health() -> contracts.WorkflowHealthItem:
    return contracts.WorkflowHealthItem(
        workflow_name="CI",
        run_count=10,
        success_rate=0.9,
        p50_seconds=120.0,
        p95_seconds=600.0,
        last_failure_at=datetime(2026, 1, 20, tzinfo=UTC),
    )


class TestEngineeringAnalyticsAPI(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

    def test_ci_cards_serializes(self) -> None:
        with mock.patch(f"{_VIEWS}.get_ci_cards", return_value=_cards()):
            response = self.client.get(self._url("ci_cards"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["open_prs"] == 5

    def test_pull_requests_serializes(self) -> None:
        with mock.patch(f"{_VIEWS}.list_pull_requests", return_value=[_pr_list_item()]) as listing:
            response = self.client.get(self._url("pull_requests"), {"date_from": "-7d"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert isinstance(body, list)
        assert body[0]["number"] == 10
        assert body[0]["ci"]["failing"] == 1
        assert listing.call_args.kwargs["date_from"] == "-7d"

    def test_pull_requests_400_on_bad_date(self) -> None:
        with mock.patch(f"{_VIEWS}.list_pull_requests", side_effect=ValueError("bad date")):
            response = self.client.get(self._url("pull_requests"), {"date_from": "garbage"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_workflow_health_serializes(self) -> None:
        with mock.patch(f"{_VIEWS}.list_workflow_health", return_value=[_workflow_health()]):
            response = self.client.get(self._url("workflow_health"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["workflow_name"] == "CI"

    def test_pr_lifecycle_serializes(self) -> None:
        with mock.patch(f"{_VIEWS}.get_pr_lifecycle", return_value=_pr_lifecycle()) as get:
            response = self.client.get(self._url("pr_lifecycle"), {"pr_number": "10", "repo": "PostHog/posthog"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["metric_quality"] == "partial"
        assert body["pull_request"]["state"] == "merged"
        assert body["events"][0]["kind"] == "opened"
        assert get.call_args.kwargs["pr_number"] == 10
        assert get.call_args.kwargs["repo"] == "PostHog/posthog"

    def test_pr_lifecycle_404_when_not_found(self) -> None:
        with mock.patch(f"{_VIEWS}.get_pr_lifecycle", return_value=None):
            response = self.client.get(self._url("pr_lifecycle"), {"pr_number": "999"})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_pr_lifecycle_400_when_pr_number_invalid(self) -> None:
        response = self.client.get(self._url("pr_lifecycle"), {"pr_number": "not-a-number"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_authentication(self) -> None:
        self.client.logout()
        response = self.client.get(self._url("pr_lifecycle"))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
