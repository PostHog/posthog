from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.skills.backend.models.skills import LLMSkill
from products.tasks.backend.constants import STORE_SKILLS_BRIDGE_STATE_KEY, STORE_SKILLS_STATE_KEY
from products.tasks.backend.logic.services.store_skills import refresh_store_skills_state
from products.tasks.backend.models import Task, TaskRun


class TestRefreshStoreSkillsState(BaseTest):
    @parameterized.expand(
        [
            (None, True, "resolved"),
            (None, None, "unchanged"),
            (False, True, "empty"),
            (False, None, "empty"),
            (None, True, "empty", True),
            (None, None, "empty", True),
        ]
    )
    def test_refresh_respects_live_context_setting(
        self, include_live_context: bool | None, flag_value: bool | None, expected: str, disable_skills: bool = False
    ) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="invoice-review",
            description="Check invoice failures.",
            body="# Invoice review\n",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        task = Task.objects.create(team=self.team, title="Review evidence", created_by=self.user)
        state: dict[str, object] = {STORE_SKILLS_STATE_KEY: [{"name": "stale-live-skill"}]}
        state["disable_skills"] = disable_skills
        if include_live_context is not None:
            state["include_live_context"] = include_live_context
        run = TaskRun.objects.create(task=task, team=self.team, state=state)

        with patch(
            "products.tasks.backend.logic.services.store_skills.posthog_feature_flag_value", return_value=flag_value
        ):
            refresh_store_skills_state(run, self.user, reason="actor_switch")

        run.refresh_from_db()
        if expected == "resolved":
            assert run.state[STORE_SKILLS_STATE_KEY] == [
                {"name": "invoice-review", "description": "Check invoice failures.", "version": 1}
            ]
            assert run.state[STORE_SKILLS_BRIDGE_STATE_KEY] is True
        elif expected == "unchanged":
            assert run.state[STORE_SKILLS_STATE_KEY] == [{"name": "stale-live-skill"}]
            assert STORE_SKILLS_BRIDGE_STATE_KEY not in run.state
        else:
            assert run.state[STORE_SKILLS_STATE_KEY] == []
            assert run.state[STORE_SKILLS_BRIDGE_STATE_KEY] is False
