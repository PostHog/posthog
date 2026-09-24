from posthog.test.base import BaseTest

from products.workflows.backend.facade.api import set_workflow_enabled
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

TRIGGER_ACTION = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {
        "type": "event",
        "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
    },
}
EXIT_ACTION = {"id": "exit_node", "name": "exit", "type": "exit", "config": {}}


class TestSetWorkflowEnabled(BaseTest):
    def test_enabling_saves_through_the_serializer_without_a_request(self) -> None:
        hog_flow = HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            status=HogFlow.State.DRAFT,
            actions=[TRIGGER_ACTION, EXIT_ACTION],
            edges=[{"from": "trigger_node", "to": "exit_node", "type": "continue"}],
            trigger=TRIGGER_ACTION["config"],
        )

        status = set_workflow_enabled(team_id=self.team.id, user_id=self.user.id, workflow_id=hog_flow.id, enabled=True)

        assert status == HogFlow.State.ACTIVE
        hog_flow.refresh_from_db()
        assert hog_flow.status == HogFlow.State.ACTIVE
