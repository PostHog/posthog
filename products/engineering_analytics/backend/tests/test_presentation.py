from datetime import UTC, date, datetime

from posthog.test.base import APIBaseTest
from unittest import mock

from parameterized import parameterized
from rest_framework import status

from products.engineering_analytics.backend.facade import contracts
from products.engineering_analytics.backend.tests.test_views import connect_github_source_without_data

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
        repo=contracts.RepoRef(provider="github", owner="PostHog", name="posthog"),
        workflow_name="CI",
        run_count=10,
        success_rate=0.9,
        p50_seconds=120.0,
        p95_seconds=600.0,
        last_failure_at=datetime(2026, 1, 20, tzinfo=UTC),
        daily=[contracts.WorkflowHealthDay(day=date(2026, 1, 20), run_count=10, completed=8, successes=7)],
    )


class TestEngineeringAnalyticsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Source resolution precedes input validation, so the non-mocked bad-input tests below
        # (window too large, malformed repo) need a connected source for those errors to surface
        # rather than the no-source error. The mocked tests bypass resolution entirely.
        connect_github_source_without_data(self.team, prefix="presentation")

    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

    def test_sources_serializes(self) -> None:
        sources = [
            contracts.GitHubSource(id="0192f000-0000-7000-8000-000000000000", repo="PostHog/posthog", prefix="older"),
            contracts.GitHubSource(
                id="0192f000-0000-7000-8000-000000000001", repo="PostHog/posthog.com", prefix="website"
            ),
        ]
        with mock.patch(f"{_VIEWS}.list_github_sources", return_value=sources):
            response = self.client.get(self._url("sources"))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [s["id"] for s in body] == [sources[0].id, sources[1].id]
        assert body[0] == {"id": sources[0].id, "repo": "PostHog/posthog", "prefix": "older"}

    def test_ci_cards_serializes(self) -> None:
        with mock.patch(f"{_VIEWS}.get_ci_cards", return_value=_cards()):
            response = self.client.get(self._url("ci_cards"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["open_prs"] == 5

    def test_no_github_source_returns_400(self) -> None:
        with mock.patch(f"{_VIEWS}.get_ci_cards", side_effect=contracts.GitHubSourceNotConnectedError()):
            response = self.client.get(self._url("ci_cards"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "GitHub" in response.json()["detail"]

    def test_ci_cards_forwards_source_id(self) -> None:
        source_id = "0192f000-0000-7000-8000-000000000000"
        with mock.patch(f"{_VIEWS}.get_ci_cards", return_value=_cards()) as get:
            response = self.client.get(self._url("ci_cards"), {"source_id": source_id})

        assert response.status_code == status.HTTP_200_OK
        assert get.call_args.kwargs["source_id"] == source_id

    def test_ci_cards_400_on_bad_source_id(self) -> None:
        with mock.patch(f"{_VIEWS}.get_ci_cards", side_effect=ValueError("source_id must be a UUID")):
            response = self.client.get(self._url("ci_cards"), {"source_id": "nope"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_pull_requests_serializes(self) -> None:
        result = contracts.PullRequestList(items=[_pr_list_item()], truncated=False, limit=1000)
        with mock.patch(f"{_VIEWS}.list_pull_requests", return_value=result) as listing:
            response = self.client.get(self._url("pull_requests"), {"date_from": "-7d"})

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["truncated"] is False
        assert body["limit"] == 1000
        assert body["items"][0]["number"] == 10
        assert body["items"][0]["ci"]["failing"] == 1
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

    def test_pr_lifecycle_400_on_malformed_repo(self) -> None:
        # Bare org (no '/name') would otherwise silently match the wrong repo.
        response = self.client.get(self._url("pr_lifecycle"), {"pr_number": "10", "repo": "PostHog"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_workflow_health_400_when_window_too_large(self) -> None:
        response = self.client.get(self._url("workflow_health"), {"date_from": "2000-01-01"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "the maximum is 366" in response.json()["detail"]

    @parameterized.expand(["sources", "ci_cards", "pull_requests", "workflow_health", "pr_lifecycle"])
    def test_requires_authentication(self, action: str) -> None:
        self.client.logout()
        response = self.client.get(self._url(action))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
