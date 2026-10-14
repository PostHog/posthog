from contextlib import suppress
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.workflows.backend.facade.contracts import NewWorkflowIdea
from products.workflows.backend.facade.workflow_ideas import create_ideas, notify_new_ideas
from products.workflows.backend.models import WorkflowIdea


def _idea(key: str) -> NewWorkflowIdea:
    return NewWorkflowIdea(
        key=key,
        title=f"Idea {key}",
        rationale="People who start a trial rarely buy a plan in the first week.",
        definition={"actions": [], "edges": []},
        evidence={"trigger_event": "trial started"},
    )


def _stored(idea_id: UUID) -> WorkflowIdea:
    return WorkflowIdea.objects.unscoped().get(id=idea_id)


class TestNotifyNewIdeas(BaseTest):
    @patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *a, **kw: flag == "real-time-notifications")
    def test_the_project_hears_about_new_ideas_once(self, _flag):
        ideas = create_ideas(team_id=self.team.id, items=[_idea("one"), _idea("two")], source="manual")
        ids = [idea.id for idea in ideas]

        assert notify_new_ideas(team_id=self.team.id, idea_ids=ids) is True
        assert all(_stored(idea_id).notified_at is not None for idea_id in ids)
        assert notify_new_ideas(team_id=self.team.id, idea_ids=ids) is False

    @parameterized.expand(
        [("flag off", {"return_value": False}), ("send fails", {"side_effect": RuntimeError("down")})]
    )
    def test_ideas_stay_unnotified_when_nothing_was_sent(self, _name: str, flag_behavior: dict):
        [idea] = create_ideas(team_id=self.team.id, items=[_idea("one")], source="manual")

        with patch("posthoganalytics.feature_enabled", **flag_behavior), suppress(RuntimeError):
            notify_new_ideas(team_id=self.team.id, idea_ids=[idea.id])

        assert _stored(idea.id).notified_at is None
