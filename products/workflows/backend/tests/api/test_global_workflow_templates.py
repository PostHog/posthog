import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.cdp.templates.fixtures import template_slack
from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models.integration import Integration

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.templates import TEMPLATE_FILES, get_global_template_by_id
from products.workflows.backend.tests.api.test_hog_flow_action_email import _email_function_template

TEMPLATES_DIR = Path(__file__).parents[2] / "templates"
WORKFLOW_FIELDS_NOT_IN_A_TEMPLATE = (
    "id",
    "team_id",
    "created_at",
    "updated_at",
    "created_by",
    "scope",
    "tags",
    "image_url",
)
TEAM_SPECIFIC_INPUT_TYPES = ("integration", "integration_multi", "integration_field")
DESTINATION_INPUT_KEYS = ("url",)


def _update_person_properties_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = "template-posthog-update-person-properties"
    template["name"] = "Update person properties"
    template["inputs_schema"] = [
        {"key": "distinct_id", "type": "string", "label": "Distinct ID", "required": True},
        {"key": "set_properties", "type": "dictionary", "label": "Set", "required": False},
        {"key": "set_once_properties", "type": "dictionary", "label": "Set once", "required": False},
    ]
    return template


def _template_id(file_name: str) -> str:
    return json.loads((TEMPLATES_DIR / file_name).read_text())["id"]


def _function_actions(template: dict) -> list[dict]:
    return [action for action in template["actions"] if action["type"].startswith("function")]


def _inputs_schema(action: dict) -> list[dict]:
    function_template = HogFunctionTemplate.get_template(action["config"]["template_id"])
    assert function_template is not None, f"Unknown function template {action['config']['template_id']}"
    return function_template.inputs_schema or []


def _person_property_filters(node: object) -> list[dict[str, object]]:
    if isinstance(node, dict):
        own = [node] if node.get("type") == "person" and "key" in node else []
        return own + [found for value in node.values() for found in _person_property_filters(value)]
    if isinstance(node, list):
        return [found for item in node for found in _person_property_filters(item)]
    return []


class TestGlobalWorkflowTemplatesGoLive(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(MOCK_NODE_TEMPLATES[0])
        sync_template_to_db(template_slack)
        sync_template_to_db(_email_function_template())
        sync_template_to_db(_update_person_properties_template())
        self.email_sender = Integration.objects.create(
            team=self.team,
            kind="email",
            config={"email": "hello@example.com", "name": "Example", "domain": "example.com", "verified": True},
        )
        self.slack_workspace = Integration.objects.create(team=self.team, kind="slack", config={"team": {"id": "T1"}})

    @parameterized.expand([(Path(file_name).stem, file_name) for file_name in TEMPLATE_FILES])
    def test_template_goes_live_once_the_person_fills_what_it_cannot_know(self, _name: str, file_name: str) -> None:
        template = get_global_template_by_id(_template_id(file_name))
        assert template is not None, f"{file_name} did not pass template validation"

        workflow = self._workflow_from(template)
        self._fill_in_the_persons_event(workflow)
        self._fill_in_the_persons_destinations(workflow)

        created = self.client.post(f"/api/projects/{self.team.id}/hog_flows", workflow)
        assert created.status_code == 201, created.json()
        enabled = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{created.json()['id']}", {"status": "active"}
        )
        assert enabled.status_code == 200, enabled.json()

    @parameterized.expand([(Path(file_name).stem, file_name) for file_name in TEMPLATE_FILES])
    def test_template_carries_no_one_elses_senders_workspaces_endpoints_or_people(
        self, _name: str, file_name: str
    ) -> None:
        template = get_global_template_by_id(_template_id(file_name))
        assert template is not None, f"{file_name} did not pass template validation"

        trigger = next(action for action in template["actions"] if action["type"] == "trigger")
        person_filters = _person_property_filters(trigger["config"])
        assert not person_filters, f"the trigger targets specific people: {person_filters}"

        for action in _function_actions(template):
            inputs = action["config"]["inputs"]
            for schema in _inputs_schema(action):
                if schema["type"] in TEAM_SPECIFIC_INPUT_TYPES or schema["key"] in DESTINATION_INPUT_KEYS:
                    assert not inputs.get(schema["key"], {}).get("value"), f"{action['name']} picks a {schema['key']}"
            sender = (inputs.get("email", {}).get("value") or {}).get("from") or {}
            assert not any(sender.get(field) for field in ("integrationId", "integrationIds", "email", "name")), (
                f"{action['name']} picks a sender"
            )

    def _workflow_from(self, template: dict) -> dict[str, Any]:
        workflow = {
            key: deepcopy(value) for key, value in template.items() if key not in WORKFLOW_FIELDS_NOT_IN_A_TEMPLATE
        }
        workflow["status"] = "draft"
        return workflow

    def _fill_in_the_persons_event(self, workflow: dict) -> None:
        trigger = next(action for action in workflow["actions"] if action["type"] == "trigger")
        if trigger["config"].get("type") == "event" and not trigger["config"].get("filters"):
            trigger["config"]["filters"] = {
                "events": [{"id": "signed up", "name": "signed up", "type": "events", "order": 0}]
            }
            workflow["trigger"] = trigger["config"]

    def _fill_in_the_persons_destinations(self, workflow: dict) -> None:
        for action in _function_actions(workflow):
            inputs = action["config"]["inputs"]
            for schema in _inputs_schema(action):
                if schema["type"] == "integration":
                    inputs[schema["key"]] = {"value": self.slack_workspace.id}
                elif schema["type"] == "integration_field":
                    inputs[schema["key"]] = {"value": "C0123"}
                elif schema["key"] in DESTINATION_INPUT_KEYS:
                    inputs[schema["key"]] = {"value": "https://example.com/webhook"}
            email = inputs.get("email", {}).get("value")
            if isinstance(email, dict) and not (email.get("from") or {}).get("integrationId"):
                email["from"] = {**(email.get("from") or {}), "integrationId": self.email_sender.id}
