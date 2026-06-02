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


class TestEngineeringAnalyticsAPI(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/engineering_analytics/{action}/"

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
