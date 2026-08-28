from posthog.test.base import BaseTest

from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.template_input_usage import get_hog_flows_referencing_template_input_keys

TEMPLATE_ID = "template-posthog-update-account-property"


def _account_property_action(properties: dict[str, str]) -> dict:
    return {
        "id": "action_1",
        "type": "function",
        "config": {"template_id": TEMPLATE_ID, "inputs": {"properties": {"value": properties}}},
    }


class TestTemplateInputUsage(BaseTest):
    def _create_flow(self, *, name: str, status: str, actions: list[dict]) -> HogFlow:
        return HogFlow.objects.create(team=self.team, name=name, status=status, actions=actions)

    def test_maps_each_referenced_key_to_its_workflows_across_statuses(self):
        draft = self._create_flow(
            name="Draft flow", status="draft", actions=[_account_property_action({"def-a": "{x}"})]
        )
        active = self._create_flow(
            name="Active flow", status="active", actions=[_account_property_action({"def-a": "1", "def-b": "2"})]
        )

        usage = get_hog_flows_referencing_template_input_keys(self.team.id, TEMPLATE_ID, "properties")

        assert {ref.id for ref in usage["def-a"]} == {str(draft.id), str(active.id)}
        assert {ref.id for ref in usage["def-b"]} == {str(active.id)}
        assert usage["def-a"][0].name in {"Draft flow", "Active flow"}
        assert usage["def-a"][0].status in {"draft", "active"}

    def test_ignores_other_templates_and_empty_or_internal_keys(self):
        self._create_flow(
            name="Other template",
            status="active",
            actions=[
                {
                    "type": "function",
                    "config": {"template_id": "template-other", "inputs": {"properties": {"value": {"def-a": "1"}}}},
                }
            ],
        )
        self._create_flow(
            name="Internal + empty",
            status="active",
            actions=[
                _account_property_action({"$$_extend_object": "{event.properties}"}),
                _account_property_action({}),
            ],
        )

        usage = get_hog_flows_referencing_template_input_keys(self.team.id, TEMPLATE_ID, "properties")

        assert usage == {}

    def test_only_value_key_scans_for_a_single_key(self):
        active = self._create_flow(
            name="Active flow", status="active", actions=[_account_property_action({"def-a": "1", "def-b": "2"})]
        )

        usage = get_hog_flows_referencing_template_input_keys(
            self.team.id, TEMPLATE_ID, "properties", only_value_key="def-a"
        )

        assert {ref.id for ref in usage["def-a"]} == {str(active.id)}
        assert "def-b" not in usage

    def test_scopes_to_team(self):
        flow = self._create_flow(name="ours", status="active", actions=[_account_property_action({"def-a": "1"})])
        assert flow  # created for self.team

        usage = get_hog_flows_referencing_template_input_keys(self.team.id + 1, TEMPLATE_ID, "properties")

        assert usage == {}
