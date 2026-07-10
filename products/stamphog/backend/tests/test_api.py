from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.team import Team

from products.stamphog.backend.models import ReviewRun, StamphogRepoConfig


class TestStamphogRepoConfigAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/repo_configs/"

    def test_create_and_retrieve(self) -> None:
        response = self.client.post(
            self.url,
            {"repository": "PostHog/posthog", "github_installation_id": "42"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["repository"] == "PostHog/posthog"
        assert body["enabled"] is True
        config = StamphogRepoConfig.objects.unscoped().get(id=body["id"])
        assert config.team_id == self.team.id

    def test_list_excludes_other_teams_configs(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        self.client.post(self.url, {"repository": "PostHog/posthog", "github_installation_id": "1"}, format="json")
        StamphogRepoConfig.objects.unscoped().create(
            team=other_team, repository="PostHog/other", github_installation_id="2"
        )

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        repos = [row["repository"] for row in response.json()["results"]]
        assert repos == ["PostHog/posthog"]

    def test_cannot_retrieve_other_teams_config(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        theirs = StamphogRepoConfig.objects.unscoped().create(
            team=other_team, repository="PostHog/other", github_installation_id="2"
        )
        response = self.client.get(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_delete_other_teams_config(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        theirs = StamphogRepoConfig.objects.unscoped().create(
            team=other_team, repository="PostHog/other", github_installation_id="2"
        )
        response = self.client.delete(f"{self.url}{theirs.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert StamphogRepoConfig.objects.unscoped().filter(id=theirs.id).exists()


class TestReviewRunAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/stamphog/review_runs/"
        self.repo_config = StamphogRepoConfig.objects.unscoped().create(
            team=self.team, repository="PostHog/posthog", github_installation_id="1"
        )

    def _make_run(self, *, team=None, repo_config=None, pr_number: int = 1, status_value: str = "queued") -> ReviewRun:
        return ReviewRun.objects.unscoped().create(
            team=team or self.team,
            repo_config=repo_config or self.repo_config,
            pr_number=pr_number,
            pr_url=f"https://github.com/PostHog/posthog/pull/{pr_number}",
            head_sha="abc123",
            status=status_value,
        )

    def test_list_only_returns_own_team_runs(self) -> None:
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        other_repo_config = StamphogRepoConfig.objects.unscoped().create(
            team=other_team, repository="PostHog/other", github_installation_id="2"
        )
        mine = self._make_run()
        self._make_run(team=other_team, repo_config=other_repo_config)

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(mine.id)]

    def test_filter_by_pr_number(self) -> None:
        self._make_run(pr_number=1)
        run_two = self._make_run(pr_number=2)

        response = self.client.get(self.url, {"pr_number": 2})
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(run_two.id)]

    def test_filter_by_status(self) -> None:
        self._make_run(pr_number=1, status_value="completed")
        queued_run = self._make_run(pr_number=2, status_value="queued")

        response = self.client.get(self.url, {"status": "queued"})
        assert response.status_code == status.HTTP_200_OK
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(queued_run.id)]

    def test_readonly_viewset_rejects_writes(self) -> None:
        # ReviewRun is created by the webhook/task pipeline, never directly
        # by API clients; the viewset must stay read-only.
        response = self.client.post(
            self.url,
            {"repository": "PostHog/posthog", "pr_number": 1, "pr_url": "x", "head_sha": "abc"},
            format="json",
        )
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
