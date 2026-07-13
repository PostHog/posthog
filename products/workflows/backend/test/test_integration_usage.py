from posthog.test.base import BaseTest

from posthog.models.integration import Integration

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.integration_usage import count_hog_flows_using_integrations


class TestHogFlowIntegrationUsage(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="slack", config={"team": {"id": "T123"}})

    def _create_flow(self, actions: list[dict], status: str = "active") -> HogFlow:
        return HogFlow.objects.create(team=self.team, name="Flow", status=status, actions=actions, edges=[])

    def _inline_action(self, integration_id: int) -> dict:
        return {
            "id": "action_1",
            "type": "function",
            "config": {"inputs": {"slack_workspace": {"value": {"integrationId": integration_id}}}},
        }

    def test_save_links_and_unlinks_integrations(self):
        flow = self._create_flow([self._inline_action(self.integration.id)])
        assert count_hog_flows_using_integrations(self.team.id, [self.integration.id]) == {self.integration.id: 1}

        flow.actions = [{"id": "action_1", "type": "delay", "config": {"duration": "5m"}}]
        flow.save()
        assert count_hog_flows_using_integrations(self.team.id, [self.integration.id]) == {}

    def test_archived_flows_are_not_counted(self):
        flow = self._create_flow([self._inline_action(self.integration.id)])
        flow.status = HogFlow.State.ARCHIVED
        flow.save()

        assert count_hog_flows_using_integrations(self.team.id, [self.integration.id]) == {}

    def test_template_typed_bare_id_inputs_are_linked(self):
        # Function actions built from a template store integration inputs as bare IDs; only the
        # template's inputs_schema marks them as integration-typed.
        HogFunctionTemplate.objects.create(
            template_id="template-slack-test",
            sha="1.0.0",
            name="Slack",
            description="",
            code="return event",
            code_language="hog",
            inputs_schema=[{"key": "slack_workspace", "type": "integration"}],
            type="destination",
            status="stable",
            category=["Integrations"],
            free=True,
        )
        self._create_flow(
            [
                {
                    "id": "action_1",
                    "type": "function",
                    "config": {
                        "template_id": "template-slack-test",
                        "inputs": {"slack_workspace": {"value": self.integration.id}},
                    },
                }
            ]
        )

        assert count_hog_flows_using_integrations(self.team.id, [self.integration.id]) == {self.integration.id: 1}

    def test_dangling_references_are_not_linked(self):
        self._create_flow([self._inline_action(self.integration.id + 1)])

        assert count_hog_flows_using_integrations(self.team.id, [self.integration.id + 1]) == {}
