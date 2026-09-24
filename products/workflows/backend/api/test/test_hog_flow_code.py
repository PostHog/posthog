from copy import deepcopy

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.team import Team

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.api.hog_flow import HogFlowCodeRequestSerializer
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

_SECRET_TEMPLATE_ID = "template-code-secret-webhook"


def _trigger_action() -> dict:
    return {
        "id": "trigger_node",
        "name": "Trigger",
        "type": "trigger",
        "config": {
            "type": "event",
            "filters": {
                "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0, "properties": []}],
                "properties": [],
                "filter_test_accounts": False,
            },
        },
    }


def _delay_action(duration: str) -> dict:
    return {"id": "wait_a_day", "name": "Wait a day", "type": "delay", "config": {"delay_duration": duration}}


def _exit_action() -> dict:
    return {"id": "exit_node", "name": "Exit", "type": "exit", "config": {"reason": "Done"}}


def _secret_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = _SECRET_TEMPLATE_ID
    template["inputs_schema"] = [
        {"key": "url", "type": "string", "label": "URL", "secret": False, "required": True},
        {"key": "api_key", "type": "string", "label": "API key", "secret": True, "required": False},
    ]
    return template


def _content(duration: str) -> dict:
    return {
        "actions": [_trigger_action(), _delay_action(duration), _exit_action()],
        "edges": [
            {"from": "trigger_node", "to": "wait_a_day", "type": "continue"},
            {"from": "wait_a_day", "to": "exit_node", "type": "continue"},
        ],
    }


class TestHogFlowCode(APIBaseTest):
    def _create_flow(self) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Welcome series", "exit_condition": "exit_only_at_end", **_content("1d")},
        )
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _code(self, flow_id: str):
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/code")

    def _code_of(self, flow_id: str, body: dict):
        return self.client.post(f"/api/projects/{self.team.id}/hog_flows/{flow_id}/code", body, format="json")

    def test_renders_the_live_definition_as_source(self) -> None:
        flow_id = self._create_flow()

        response = self._code(flow_id)

        no_key = (
            "This workflow has no key, so the copied file invents one from its name. The first push creates "
            "a new draft workflow. Turn the original workflow off or delete it after that push."
        )
        assert response.status_code == 200, response.json()
        assert response.json() == {
            "language": "typescript",
            "code": (
                "// @posthog/workflows cannot express everything in this workflow. Review these before you push:\n"
                f"// - {no_key}\n"
                "\n"
                "import { delay, onEvent, path, workflow } from '@posthog/workflows'\n"
                "\n"
                "export const welcomeSeries = workflow({\n"
                "    key: 'welcome-series',\n"
                "    name: 'Welcome series',\n"
                "    on: onEvent({ event: '$pageview' }),\n"
                "    steps: path(delay('1d', { name: 'Wait a day' })),\n"
                "    exit: { reason: 'Done' },\n"
                "})\n"
            ),
            "warnings": [{"action_id": None, "message": no_key}],
        }

    def test_prefers_the_staged_draft_over_the_live_definition(self) -> None:
        flow_id = self._create_flow()
        activated = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {"status": "active"})
        assert activated.status_code == 200, activated.json()
        staged = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow_id}", {**_content("2d"), "stage_draft": True}
        )
        assert staged.status_code == 200, staged.json()
        assert HogFlow.objects.get(pk=flow_id).draft is not None

        response = self._code(flow_id)

        assert response.status_code == 200, response.json()
        assert "delay('2d', { name: 'Wait a day' })" in response.json()["code"]
        assert "'1d'" not in response.json()["code"]

        renamed = self._code_of(flow_id, {"name": "Renamed"})

        assert renamed.status_code == 200, renamed.json()
        assert "name: 'Renamed'" in renamed.json()["code"]
        assert "delay('2d', { name: 'Wait a day' })" in renamed.json()["code"]

    def test_renders_unsaved_edits_without_storing_them(self) -> None:
        flow_id = self._create_flow()
        before = HogFlow.objects.get(pk=flow_id)

        response = self._code_of(flow_id, _content("3d"))

        assert response.status_code == 200, response.json()
        assert "delay('3d', { name: 'Wait a day' })" in response.json()["code"]
        assert "name: 'Welcome series'" in response.json()["code"]
        after = HogFlow.objects.get(pk=flow_id)
        assert (after.actions, after.draft, after.version, after.updated_at) == (
            before.actions,
            before.draft,
            before.version,
            before.updated_at,
        )

    def test_rejects_a_body_the_renderer_cannot_read(self) -> None:
        flow_id = self._create_flow()

        response = self._code_of(flow_id, {"actions": [{"type": "delay"}]})

        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "actions"
        assert response.json()["detail"] == "Step 0 needs a text `id` and a text `type`."

    def test_rejects_a_branch_edge_past_the_arms_of_a_stored_step(self) -> None:
        flow_id = self._create_flow()
        edges = [
            *_content("1d")["edges"],
            {"from": "wait_a_day", "to": "exit_node", "type": "branch", "index": 2147483647},
        ]

        response = self._code_of(flow_id, {"edges": edges})

        assert response.status_code == 400, response.json()
        assert response.json()["attr"] == "edges"

    def test_renders_a_secret_in_the_body_as_the_stored_secret(self) -> None:
        sync_template_to_db(_secret_template())
        function_step = {
            "id": "send_it",
            "name": "Send it",
            "type": "function",
            "config": {
                "template_id": _SECRET_TEMPLATE_ID,
                "inputs": {"url": {"value": "https://example.com"}, "api_key": {"value": "STORED-SECRET"}},
            },
        }
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {
                "name": "Secret flow",
                "actions": [_trigger_action(), function_step, _exit_action()],
                "edges": [
                    {"from": "trigger_node", "to": "send_it", "type": "continue"},
                    {"from": "send_it", "to": "exit_node", "type": "continue"},
                ],
            },
            format="json",
        )
        assert created.status_code == 201, created.json()
        flow_id = created.json()["id"]
        editor_actions = deepcopy(created.json()["actions"])
        next(action for action in editor_actions if action["id"] == "send_it")["config"]["inputs"]["api_key"] = {
            "value": "TYPED-SECRET"
        }

        stored = self._code(flow_id)
        unsaved = self._code_of(flow_id, {"actions": editor_actions})

        assert unsaved.status_code == 200, unsaved.json()
        assert unsaved.json() == stored.json()
        assert "secret('SEND_IT_API_KEY')" in unsaved.json()["code"]
        assert "TYPED-SECRET" not in unsaved.content.decode()
        assert "STORED-SECRET" not in unsaved.content.decode()

    def test_hides_another_teams_workflow(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        flow = HogFlow.objects.create(team=other_team, name="Theirs", **_content("1d"))

        response = self._code(str(flow.id))

        # A missing route is a 404 too, so the body has to say the object was not found.
        assert response.status_code == 404
        assert response.json()["detail"] == "Not found."


class TestHogFlowCodeRequestSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("actions_not_a_list", {"actions": {"id": "a"}}, "actions"),
            ("action_not_an_object", {"actions": ["a"]}, "actions"),
            ("action_without_an_id", {"actions": [{"type": "delay"}]}, "actions"),
            ("config_not_an_object", {"actions": [{"id": "a", "type": "delay", "config": []}]}, "actions"),
            (
                "inputs_not_an_object",
                {"actions": [{"id": "a", "type": "function", "config": {"inputs": []}}]},
                "actions",
            ),
            (
                "conditions_not_a_list",
                {"actions": [{"id": "a", "type": "conditional_branch", "config": {"conditions": 3}}]},
                "actions",
            ),
            ("edge_not_an_object", {"edges": ["a"]}, "edges"),
            (
                "branch_edge_past_the_arms",
                {
                    "actions": [{"id": "a", "type": "conditional_branch", "config": {"conditions": [{}]}}],
                    "edges": [{"from": "a", "to": "b", "type": "branch", "index": 1}],
                },
                "edges",
            ),
            ("variables_not_a_list", {"variables": "a"}, "variables"),
            ("conversion_not_an_object", {"conversion": []}, "conversion"),
            ("unknown_exit_condition", {"exit_condition": "never"}, "exit_condition"),
        ]
    )
    def test_rejects_a_shape_the_renderer_cannot_read(self, _name: str, body: dict, field: str) -> None:
        serializer = HogFlowCodeRequestSerializer(data=body)

        assert not serializer.is_valid()
        assert list(serializer.errors) == [field]

    def test_accepts_a_half_finished_step(self) -> None:
        serializer = HogFlowCodeRequestSerializer(data={"actions": [{"id": "new_step", "type": "function"}]})

        assert serializer.is_valid(), serializer.errors
