from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.utils import generate_short_id

from products.product_analytics.backend.facade.api import get_or_create_saved_insight
from products.today.backend.facade.api import get_work_threads
from products.workflows.backend.facade.testing import create_workflow_for_test

FLAG_PATCH = "products.release.backend.facade.api.releases_enabled"


class TestReleaseWorkSource(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        enabled = patch(FLAG_PATCH, return_value=True)
        enabled.start()
        self.addCleanup(enabled.stop)

    def _flag(self, key: str, rollout: int) -> int:
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": key, "filters": {"groups": [{"properties": [], "rollout_percentage": rollout}]}},
            format="json",
        )
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _release(self, name: str, flag_ids: list[int]) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/releases/", {"name": name, "feature_flag_ids": flag_ids}, format="json"
        )
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    @parameterized.expand([("by_ref", True), ("in_flight", False)])
    def test_finds_the_thread_of_a_release_through_today(self, _name: str, by_ref: bool) -> None:
        partial_flag = self._flag("quiet-theme", 50)
        partial = self._release("Quiet theme", [partial_flag])
        ended_flag = self._flag("old-theme", 100)
        self._release("Old theme", [ended_flag])
        archived = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{ended_flag}/",
            {"archived": True, "active": False},
            format="json",
        )
        assert archived.status_code == 200, archived.json()

        threads = get_work_threads(
            team=self.team, user=self.user, source="release", ref=partial if by_ref else None, scopes=None
        )

        assert [(thread.key, thread.line.steps[-1].options[0].label) for thread in threads] == [
            (f"release:{partial}", "Roll out to more users")
        ]
        assert threads[0].line.steps[-1].options[0].helper.run.params == {"flag_id": partial_flag}

    @parameterized.expand(
        [("unknown_ref", "0193a000-0000-7000-8000-00000000abcd", True), ("releases_off", None, False)]
    )
    def test_finds_nothing_for_an_unknown_release_or_when_releases_are_off(
        self, _name: str, ref: str | None, enabled: bool
    ) -> None:
        self._release("Quiet theme", [self._flag("quiet-theme", 50)])

        with patch(FLAG_PATCH, return_value=enabled):
            threads = get_work_threads(team=self.team, user=self.user, source="release", ref=ref, scopes=None)

        assert threads == []

    @parameterized.expand(
        [
            ("not_limited_by_scopes", None, ["survey", "insight", "broadcast"]),
            ("full_access", ["*"], ["survey", "insight", "broadcast"]),
            ("flags_only", ["today:read", "feature_flag:read"], []),
            ("flags_and_surveys", ["today:read", "feature_flag:read", "survey:read"], ["survey"]),
            ("flags_and_insights", ["today:read", "feature_flag:read", "insight:read"], ["insight"]),
            ("flags_and_workflows", ["today:read", "feature_flag:read", "hog_flow:read"], ["broadcast"]),
        ]
    )
    def test_linked_surveys_insights_and_broadcasts_follow_the_key_scopes(
        self, _name: str, scopes: list[str] | None, shown: list[str]
    ) -> None:
        survey = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            {"name": "Feedback", "type": "popover", "questions": [{"type": "open", "question": "How is it?"}]},
            format="json",
        )
        assert survey.status_code == 201, survey.json()
        insight_id, _ = get_or_create_saved_insight(
            team_id=self.team.id,
            user_id=self.user.id,
            short_id=generate_short_id(),
            name="Adoption",
            description=None,
            query=None,
        )
        broadcast_id = create_workflow_for_test(team_id=self.team.id, name="Launch email").id
        release = self.client.post(
            f"/api/projects/{self.team.id}/releases/",
            {
                "name": "Quiet theme",
                "feature_flag_ids": [self._flag("quiet-theme", 50)],
                "survey_ids": [survey.json()["id"]],
                "insight_ids": [insight_id],
                "broadcast_ids": [str(broadcast_id)],
            },
            format="json",
        )
        assert release.status_code == 201, release.json()

        threads = get_work_threads(
            team=self.team,
            user=self.user,
            source="release",
            ref=release.json()["id"],
            scopes=None if scopes is None else frozenset(scopes),
        )

        lines = threads[0].line.steps[-1].alongside
        assert [line.key.split(":")[0] for line in lines] == shown
