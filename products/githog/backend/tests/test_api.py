from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import User

from products.githog.backend.models import GitHogPullRequestMessage


class TestGitHogPullRequestMessagesAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        base = f"/api/environments/{self.team.id}/githog/pull_request_messages"
        return f"{base}{suffix}"

    def test_list_returns_only_messages_for_team_repo_and_pr(self):
        other_team_org = self.organization
        other_team = self.create_team_with_organization(other_team_org)
        GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=1, body="hello"
        )
        GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=2, body="other PR"
        )
        GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/other", pr_number=1, body="other repo"
        )
        GitHogPullRequestMessage.objects.create(
            team=other_team, author=self.user, repository="acme/repo", pr_number=1, body="other team"
        )

        response = self.client.get(self._url(), {"repository": "acme/repo", "number": 1})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["repository"] == "acme/repo"
        assert data["pr_number"] == 1
        assert [m["body"] for m in data["messages"]] == ["hello"]
        assert data["messages"][0]["is_mine"] is True
        assert data["messages"][0]["author_id"] == self.user.id

    def test_create_persists_message_with_author(self):
        response = self.client.post(
            self._url(),
            data={"repository": "acme/repo", "number": 7, "body": "  first comment  "},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        data = response.json()
        assert data["body"] == "first comment"
        assert data["author_id"] == self.user.id
        assert data["is_mine"] is True
        assert data["edited_at"] is None

        row = GitHogPullRequestMessage.objects.get(id=data["id"])
        assert row.team_id == self.team.id
        assert row.repository == "acme/repo"
        assert row.pr_number == 7
        assert row.body == "first comment"

    def test_create_rejects_blank_body(self):
        response = self.client.post(
            self._url(),
            data={"repository": "acme/repo", "number": 1, "body": "   "},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_patch_only_author_can_edit(self):
        other = User.objects.create_user(email="other@posthog.com", first_name="Other", password="x")
        msg = GitHogPullRequestMessage.objects.create(
            team=self.team, author=other, repository="acme/repo", pr_number=1, body="original"
        )
        response = self.client.patch(
            self._url(f"/{msg.id}"),
            data={"body": "edited"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_patch_sets_edited_at(self):
        msg = GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=1, body="original"
        )
        response = self.client.patch(
            self._url(f"/{msg.id}"),
            data={"body": "updated text"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["body"] == "updated text"
        assert data["edited_at"] is not None

    def test_delete_only_author_can_delete(self):
        other = User.objects.create_user(email="other2@posthog.com", first_name="Other", password="x")
        msg = GitHogPullRequestMessage.objects.create(
            team=self.team, author=other, repository="acme/repo", pr_number=1, body="original"
        )
        response = self.client.delete(self._url(f"/{msg.id}"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert GitHogPullRequestMessage.objects.filter(id=msg.id).exists()

    def test_delete_removes_own_message(self):
        msg = GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=1, body="original"
        )
        response = self.client.delete(self._url(f"/{msg.id}"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not GitHogPullRequestMessage.objects.filter(id=msg.id).exists()

    def test_list_returns_oldest_first(self):
        first = GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=1, body="first"
        )
        second = GitHogPullRequestMessage.objects.create(
            team=self.team, author=self.user, repository="acme/repo", pr_number=1, body="second"
        )

        response = self.client.get(self._url(), {"repository": "acme/repo", "number": 1})
        assert response.status_code == status.HTTP_200_OK
        ids = [m["id"] for m in response.json()["messages"]]
        assert ids == [first.id, second.id]
