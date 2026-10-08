from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.review_hog.backend.models import ReviewRepository


class TestReviewRepositoryAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.url = f"/api/projects/{self.team.id}/review_hog/repositories/"

    def _activity(self, repository_id: str) -> list[ActivityLog]:
        return list(
            ActivityLog.objects.filter(team_id=self.team.id, scope="ReviewRepository", item_id=repository_id).order_by(
                "created_at"
            )
        )

    def test_add_change_and_remove_a_repository_are_logged(self) -> None:
        created = self.client.post(self.url, {"full_name": "PostHog/posthog-js"}, format="json")

        assert created.status_code == 201, created.json()
        repository_id = created.json()["id"]
        assert created.json()["flash_for"] == "everyone"
        assert created.json()["my_result"] == {"mode": "flash", "reason": "everyone"}
        duplicate = self.client.post(self.url, {"full_name": "posthog/POSTHOG-JS"}, format="json")
        assert duplicate.status_code == 400

        changed = self.client.patch(f"{self.url}{repository_id}/", {"flash_for": "listed"}, format="json")

        assert changed.status_code == 200, changed.json()
        assert changed.json()["my_result"] == {"mode": "none", "reason": "not_listed"}

        assert self.client.delete(f"{self.url}{repository_id}/").status_code == 204

        activity = self._activity(repository_id)
        assert [(row.activity, row.user_id) for row in activity] == [
            ("created", self.user.id),
            ("updated", self.user.id),
            ("deleted", self.user.id),
        ]
        update_detail = activity[1].detail
        assert update_detail is not None
        changes = update_detail["changes"]
        assert [(change["field"], change["before"], change["after"]) for change in changes] == [
            ("flash_for", "everyone", "listed")
        ]

    def test_people_lists_drive_the_result_and_are_logged_on_the_repository(self) -> None:
        repository = ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, full_name="PostHog/posthog-js", flash_for=ReviewRepository.FlashFor.LISTED
        )
        people_url = f"{self.url}{repository.id}/people/"

        added = self.client.post(people_url, {"user_id": self.user.id, "kind": "listed"}, format="json")

        assert added.status_code == 201, added.json()
        assert added.json()["my_result"] == {"mode": "flash", "reason": "listed"}
        person_id = added.json()["people"][0]["id"]
        assert (
            self.client.post(people_url, {"user_id": self.user.id, "kind": "listed"}, format="json").status_code == 200
        )

        removed = self.client.delete(f"{people_url}{person_id}/")

        assert removed.status_code == 200, removed.json()
        assert removed.json()["people"] == []
        assert removed.json()["my_result"] == {"mode": "none", "reason": "not_listed"}
        changes = [
            (row.detail or {})["changes"][0] for row in self._activity(str(repository.id)) if row.activity == "updated"
        ]
        assert [(change["action"], change["field"]) for change in changes] == [
            ("created", "listed_people"),
            ("deleted", "listed_people"),
        ]

        outsider = User.objects.create_and_join(Organization.objects.create(name="other"), "out@example.com", None)
        rejected = self.client.post(people_url, {"user_id": outsider.id, "kind": "listed"}, format="json")
        assert rejected.status_code == 400

    def test_my_choice_wins_over_the_repository_until_cleared(self) -> None:
        repository = ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, full_name="PostHog/posthog", flash_for=ReviewRepository.FlashFor.EVERYONE
        )
        choice_url = f"{self.url}{repository.id}/my_choice/"

        set_off = self.client.put(choice_url, {"mode": "off"}, format="json")

        assert set_off.status_code == 200, set_off.json()
        assert set_off.json()["my_choice"] == "off"
        assert set_off.json()["my_result"] == {"mode": "none", "reason": "own_repository_choice"}

        cleared = self.client.delete(choice_url)

        assert cleared.status_code == 200
        assert cleared.json()["my_choice"] is None
        assert cleared.json()["my_result"] == {"mode": "flash", "reason": "everyone"}

    def test_repositories_of_another_project_are_invisible(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="other"))
        other = ReviewRepository.objects.for_team(other_team.id).create(
            team=other_team, full_name="Other/repo", flash_for=ReviewRepository.FlashFor.LISTED
        )

        listed = self.client.get(self.url)
        changed = self.client.patch(f"{self.url}{other.id}/", {"flash_for": "everyone"}, format="json")

        assert listed.status_code == 200
        assert listed.json() == []
        assert changed.status_code == 404
        other.refresh_from_db()
        assert other.flash_for == ReviewRepository.FlashFor.LISTED
