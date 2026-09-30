import json
from copy import deepcopy
from textwrap import dedent
from typing import Any, Optional

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import yaml
from jsonschema import Draft202012Validator
from parameterized import parameterized
from rest_framework import status

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision

IN_FLIGHT_COUNT = "products.workflows.backend.presentation.views.hog_flow.get_hog_flow_in_flight_count"
REPORT_USER_ACTION = "products.workflows.backend.presentation.views.hog_flow_code.report_user_action"

# Far above any id the integrations sequence hands out in a test run, so an explicit id never collides.
SAMPLE_SENDER_ID = 9_000_012

SAMPLE = dedent(
    """\
    version: 1
    key: trial-upgrade-nudge
    name: Trial upgrade nudge
    trigger:
      type: event
      event: trial started
    steps:
      - type: delay
        name: Wait three days
        duration: 3d
      - type: branch
        name: Which plan?
        arms:
          - name: Upgraded to pro
            when:
              - { person: plan, operator: exact, value: [pro] }
            then:
              - type: email
                name: Thank the new customer
                from: { integration_ids: [9000012], name: The Example team }
                to: '{{ person.properties.email }}'
                subject: Thanks for upgrading
                text: Your pro plan is live.
                html: <p>Your pro plan is live.</p>
          - name: Still on trial
            when:
              - { person: plan, operator: exact, value: [trial] }
            then:
              - type: webhook
                id: tell_the_crm
                name: Tell the CRM
                url: https://example.com/hooks/trial
                body:
                  distinct_id: '{event.distinct_id}'
    exit:
      reason: Trial nudge finished
    """
)

# The sample as a person would have sent it to the workflows API. It is the wiring the compiler must
# reproduce: slug ids, continue edges in order, one branch edge per arm, and the email mapping.
SAMPLE_DEFINITION: dict[str, Any] = {
    "name": "Trial upgrade nudge",
    "description": "",
    "status": "draft",
    "exit_condition": "exit_only_at_end",
    "variables": [],
    "actions": [
        {
            "id": "trigger_node",
            "name": "Trigger",
            "description": "",
            "type": "trigger",
            "config": {
                "type": "event",
                "filters": {
                    "events": [
                        {"id": "trial started", "name": "trial started", "type": "events", "order": 0, "properties": []}
                    ],
                    "properties": [],
                    "filter_test_accounts": False,
                },
            },
        },
        {
            "id": "wait_three_days",
            "name": "Wait three days",
            "description": "",
            "type": "delay",
            "config": {"delay_duration": "3d"},
        },
        {
            "id": "which_plan",
            "name": "Which plan?",
            "description": "",
            "type": "conditional_branch",
            "config": {
                "conditions": [
                    {
                        "name": "Upgraded to pro",
                        "filters": {
                            "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": ["pro"]}]
                        },
                    },
                    {
                        "name": "Still on trial",
                        "filters": {
                            "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": ["trial"]}]
                        },
                    },
                ]
            },
        },
        {
            "id": "thank_the_new_customer",
            "name": "Thank the new customer",
            "description": "",
            "type": "function_email",
            "config": {
                "template_id": "template-email",
                "inputs": {
                    "email": {
                        "value": {
                            "from": {"integrationIds": [SAMPLE_SENDER_ID], "name": "The Example team"},
                            "to": {"email": "{{ person.properties.email }}", "name": ""},
                            "subject": "Thanks for upgrading",
                            "text": "Your pro plan is live.",
                            "html": "<p>Your pro plan is live.</p>",
                        },
                        "templating": "liquid",
                    }
                },
            },
        },
        {
            "id": "tell_the_crm",
            "name": "Tell the CRM",
            "description": "",
            "type": "function",
            "config": {
                "template_id": "template-webhook",
                "inputs": {
                    "url": {"value": "https://example.com/hooks/trial"},
                    "method": {"value": "POST"},
                    "body": {"value": {"distinct_id": "{event.distinct_id}"}},
                },
            },
        },
        {
            "id": "exit_node",
            "name": "Exit",
            "description": "",
            "type": "exit",
            "config": {"reason": "Trial nudge finished"},
        },
    ],
    "edges": [
        {"from": "trigger_node", "to": "wait_three_days", "type": "continue"},
        {"from": "wait_three_days", "to": "which_plan", "type": "continue"},
        {"from": "which_plan", "to": "exit_node", "type": "continue"},
        {"from": "thank_the_new_customer", "to": "exit_node", "type": "continue"},
        {"from": "which_plan", "to": "thank_the_new_customer", "type": "branch", "index": 0},
        {"from": "tell_the_crm", "to": "exit_node", "type": "continue"},
        {"from": "which_plan", "to": "tell_the_crm", "type": "branch", "index": 1},
    ],
}

# A small valid file the error cases below break one line at a time.
BASE = dedent(
    """\
    version: 1
    key: welcome
    name: Welcome
    trigger:
      type: event
      event: signed up
    steps:
      - type: delay
        name: Wait a day
        duration: 1d
    """
)

WEBHOOK_STEP_WITH_SECRET = """\
  - type: function
    name: Tell the CRM
    template: template-webhook
    inputs:
      url: https://example.com/hooks
      signing_secret: not-a-real-secret
"""

SECOND_WAIT_A_DAY = """\
  - type: delay
    name: Wait a day
    duration: 2d
"""


def _base_document(**changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "version": 1,
        "key": "welcome",
        "name": "Welcome",
        "trigger": {"type": "event", "event": "signed up"},
        "steps": [{"type": "delay", "name": "Wait a day", "duration": "1d"}],
    }
    document.update(changes)
    return {key: value for key, value in document.items() if value is not None}


def _webhook_template_with_signing_secret() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["inputs_schema"] = [
        *template["inputs_schema"],
        {"key": "signing_secret", "type": "string", "label": "Signing secret", "secret": True, "required": False},
    ]
    return template


def _email_template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template["id"] = "template-email"
    template["name"] = "Email"
    template["inputs_schema"] = [
        {"key": "email", "type": "native_email", "label": "Email", "secret": False, "required": True}
    ]
    return template


PLAIN_EMAIL_STEP = dedent(
    """\
    version: 1
    key: plain-email
    name: Plain email
    trigger:
      type: event
      event: signed up
    steps:
      - type: step
        name: Email
        action_type: function_email
        config:
          template_id: template-email
          inputs:
            email:
              value:
                from: SENDER
                to: { email: '{{ person.properties.email }}', name: '' }
                subject: Welcome
                text: Welcome aboard.
              templating: liquid
    """
)


def _create_integration(team: Team, integration_id: int, kind: str = "email") -> Integration:
    return Integration.objects.create(
        id=integration_id,
        team=team,
        kind=kind,
        integration_id=f"sender-{integration_id}.example.com",
        config={"domain": f"sender-{integration_id}.example.com", "verified": True},
    )


def _set_up_project(team: Team) -> None:
    sync_template_to_db(_webhook_template_with_signing_secret())
    sync_template_to_db(_email_template())
    _create_integration(team, SAMPLE_SENDER_ID)


def _create_keyed_workflow(client: Any, team: Team, key: str, definition: dict[str, Any]) -> HogFlow:
    response = client.post(f"/api/projects/{team.id}/hog_flows", definition, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.json()
    HogFlow.objects.filter(id=response.json()["id"]).update(key=key)
    return HogFlow.objects.get(id=response.json()["id"])


def _in_flight(by_action: dict[str, int]) -> MagicMock:
    response = MagicMock(status_code=200)
    response.json.return_value = {"count": sum(by_action.values()), "by_action": by_action, "position_unknown": 0}
    return response


class TestHogFlowCodeCheck(APIBaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        _set_up_project(cls.team)

    def _check(self, content: str, **kwargs: Any) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_check/", {"content": content}, format="json", **kwargs
        )

    def _create_workflow(self, key: str, definition: dict[str, Any], team: Optional[Team] = None) -> HogFlow:
        return _create_keyed_workflow(self.client, team or self.team, key, definition)

    def test_code_schema_is_a_draft_2020_12_schema_the_sample_satisfies(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/code_schema/")

        assert response.status_code == status.HTTP_200_OK
        schema = response.json()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert list(Draft202012Validator(schema).iter_errors(yaml.safe_load(SAMPLE))) == []

    def test_check_of_a_new_key_plans_a_create_with_every_step_added(self) -> None:
        response = self._check(SAMPLE)

        assert response.status_code == status.HTTP_200_OK, response.json()
        plan = response.json()["plan"]
        assert plan["result"] == "create"
        assert plan["workflow"] is None
        assert [step["id"] for step in plan["added_steps"]] == [
            "wait_three_days",
            "which_plan",
            "thank_the_new_customer",
            "tell_the_crm",
        ]
        assert plan["changed_steps"] == []
        assert plan["removed_steps"] == []
        assert response.json()["warnings"] == []

    @parameterized.expand([("as_the_api_stores_it", False), ("as_the_editor_stores_it", True)])
    @patch(IN_FLIGHT_COUNT)
    def test_check_of_a_file_matching_the_stored_workflow_is_unchanged(
        self, _name: str, editor_shape: bool, mock_count: MagicMock
    ) -> None:
        workflow = self._create_workflow("trial-upgrade-nudge", SAMPLE_DEFINITION)
        stored_email = next(a for a in workflow.actions if a["id"] == "thank_the_new_customer")
        assert "design" in stored_email["config"]["inputs"]["email"]["value"]
        if editor_shape:
            HogFlow.objects.filter(id=workflow.id).update(
                actions=[
                    {**action, "created_at": 1700000000000, "updated_at": 1700000000000} for action in workflow.actions
                ],
                edges=list(reversed(workflow.edges)),
                variables=None,
            )

        response = self._check(SAMPLE)

        assert response.status_code == status.HTTP_200_OK, response.json()
        plan = response.json()["plan"]
        assert plan["result"] == "unchanged", plan
        assert plan["workflow"]["id"] == str(workflow.id)
        assert plan["workflow"]["key"] == "trial-upgrade-nudge"
        assert (plan["added_steps"], plan["changed_steps"], plan["removed_steps"], plan["changed_fields"]) == (
            [],
            [],
            [],
            [],
        )
        mock_count.assert_not_called()

    @patch(IN_FLIGHT_COUNT)
    def test_check_of_a_renamed_step_reports_where_its_people_go_and_how_to_keep_them(self, mock_count) -> None:
        workflow = self._create_workflow("trial-upgrade-nudge", SAMPLE_DEFINITION)
        mock_count.return_value = _in_flight({"wait_three_days": 41, "which_plan": 16})
        revisions_before = HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow=workflow).count()
        activity_before = ActivityLog.objects.filter(scope="HogFlow").count()

        response = self._check(SAMPLE.replace("name: Wait three days", "name: Wait a few days"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        plan = response.json()["plan"]
        assert plan["result"] == "update"
        assert plan["added_steps"] == [{"id": "wait_a_few_days", "name": "Wait a few days", "type": "delay"}]
        assert plan["removed_steps"] == [
            {
                "action_id": "wait_three_days",
                "name": "Wait three days",
                "runs": 41,
                "moves_to": {"action_id": "which_plan", "name": "Which plan?"},
                "exits": False,
            }
        ]
        assert plan["in_flight_runs"] == 57
        [warning] = response.json()["warnings"]
        assert "id: wait_three_days" in warning["fix"]

        workflow.refresh_from_db()
        assert [a["id"] for a in workflow.actions][1] == "wait_three_days"
        assert HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow=workflow).count() == revisions_before
        assert ActivityLog.objects.filter(scope="HogFlow").count() == activity_before
        assert HogFlow.objects.filter(team=self.team).count() == 1

    def test_check_reports_a_changed_step_by_the_fields_that_differ(self) -> None:
        self._create_workflow("trial-upgrade-nudge", SAMPLE_DEFINITION)

        response = self._check(SAMPLE.replace("duration: 3d", "duration: 5d").replace("Trial upgrade", "Trial"))

        plan = response.json()["plan"]
        assert plan["result"] == "update"
        assert plan["changed_fields"] == ["name"]
        assert plan["changed_steps"] == [
            {"id": "wait_three_days", "name": "Wait three days", "type": "delay", "changes": ["config.delay_duration"]}
        ]

    @parameterized.expand(
        [
            ("check_another_projects_sender", "code_check", True, "email", "typed"),
            ("apply_another_projects_sender", "code_apply", True, "email", "typed"),
            ("check_this_projects_slack_integration", "code_check", False, "slack", "typed"),
            ("apply_another_projects_sender_in_a_plain_step", "code_apply", True, "email", "plain"),
            ("apply_another_projects_sender_as_text_in_a_plain_step", "code_apply", True, "email", "plain_text_id"),
        ]
    )
    def test_an_email_sender_the_project_does_not_have_is_refused_at_its_step(
        self, _name: str, endpoint: str, in_other_project: bool, kind: str, step: str
    ) -> None:
        team = (
            Team.objects.create(organization=self.organization, name="Other project") if in_other_project else self.team
        )
        sender = _create_integration(team, SAMPLE_SENDER_ID + 1, kind=kind)
        plain_senders = {
            "plain": f"{{ integrationId: {sender.id}, integrationIds: [{sender.id}] }}",
            "plain_text_id": f"{{ integrationId: '{sender.id}' }}",
        }
        if step == "typed":
            content = SAMPLE.replace(f"integration_ids: [{SAMPLE_SENDER_ID}]", f"integration_ids: [{sender.id}]")
            located = ("steps[1].arms[0].then[0].from.integration_ids", 20)
        else:
            content = PLAIN_EMAIL_STEP.replace("SENDER", plain_senders[step])
            located = ("steps[0].config.inputs.email.value.from", 16)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{endpoint}/", {"content": content}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        [error] = response.json()["errors"]
        assert (error["status"], error["path"], error["line"]) == ("invalid_value", *located), error
        assert str(sender.id) in error["message"]
        assert not HogFlow.objects.filter(team=self.team).exists()

    def test_a_key_in_another_project_is_never_found(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        self._create_workflow("trial-upgrade-nudge", SAMPLE_DEFINITION, team=other_team)

        response = self._check(SAMPLE)

        assert response.json()["plan"]["result"] == "create"

    @parameterized.expand(
        [
            ("string_field_given_a_number", BASE.replace("name: Welcome", "name: 1.10"), "invalid_value", "name", 3, 7),
            (
                "escaped_lone_surrogate",
                BASE.replace("key: welcome", 'key: "\\ud800"'),
                "invalid_value",
                "key",
                2,
                6,
            ),
            (
                "version_written_as_a_float",
                BASE.replace("version: 1", "version: 1.0"),
                "unsupported_version",
                "version",
                1,
                10,
            ),
            (
                "duplicate_key",
                BASE.replace("name: Welcome\n", "name: Welcome\nname: Welcome again\n"),
                "duplicate_key",
                "name",
                4,
                1,
            ),
            (
                "alias",
                BASE.replace("name: Welcome\n", "name: &title Welcome\ndescription: *title\n"),
                "yaml_feature_not_allowed",
                "description",
                4,
                14,
            ),
            ("missing_name", BASE.replace("name: Welcome\n", ""), "missing_field", "name", 1, 1),
            (
                "unknown_field",
                BASE.replace("name: Welcome\n", "name: Welcome\ncolour: blue\n"),
                "unknown_field",
                "colour",
                4,
                1,
            ),
            ("unknown_step_type", BASE.replace("type: delay", "type: sms"), "unknown_type", "steps[0].type", 8, 11),
            (
                "delay_over_30_days",
                BASE.replace("duration: 1d", "duration: 40d"),
                "invalid_value",
                "steps[0].duration",
                10,
                15,
            ),
            ("two_steps_with_one_id", BASE + SECOND_WAIT_A_DAY, "duplicate_step_id", "steps[1].name", 12, 11),
            (
                "secret_input_value",
                BASE + WEBHOOK_STEP_WITH_SECRET,
                "secret_input",
                "steps[1].inputs.signing_secret",
                16,
                23,
            ),
        ]
    )
    def test_each_mistake_in_a_yaml_file_is_one_located_error(
        self, _name: str, content: str, error_status: str, path: str, line: int, column: int
    ) -> None:
        response = self._check(content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        [error] = response.json()["errors"]
        assert (error["status"], error["path"], error["line"], error["column"]) == (error_status, path, line, column)
        assert error["message"] and error["why"] and error["fix"]

    @parameterized.expand(
        [
            ("string_field_given_a_number", json.dumps(_base_document(name=1.10)), "invalid_value", "name"),
            (
                "duplicate_key",
                json.dumps(_base_document()).replace('"name": "Welcome"', '"name": "Welcome", "name": "Again"'),
                "duplicate_key",
                "name",
            ),
            ("missing_name", json.dumps(_base_document(name=None)), "missing_field", "name"),
            ("unknown_field", json.dumps(_base_document(colour="blue")), "unknown_field", "colour"),
            (
                "unknown_step_type",
                json.dumps(_base_document(steps=[{"type": "sms", "name": "Wait a day"}])),
                "unknown_type",
                "steps[0].type",
            ),
            (
                "delay_over_30_days",
                json.dumps(_base_document(steps=[{"type": "delay", "name": "Wait a day", "duration": "40d"}])),
                "invalid_value",
                "steps[0].duration",
            ),
            (
                "two_steps_with_one_id",
                json.dumps(
                    _base_document(
                        steps=[
                            {"type": "delay", "name": "Wait a day", "duration": "1d"},
                            {"type": "delay", "name": "Wait a day", "duration": "2d"},
                        ]
                    )
                ),
                "duplicate_step_id",
                "steps[1].name",
            ),
            (
                "secret_input_value",
                json.dumps(
                    _base_document(
                        steps=[
                            {
                                "type": "function",
                                "name": "Tell the CRM",
                                "template": "template-webhook",
                                "inputs": {"url": "https://example.com/hooks", "signing_secret": "not-a-real-secret"},
                            }
                        ]
                    )
                ),
                "secret_input",
                "steps[0].inputs.signing_secret",
            ),
        ]
    )
    def test_each_mistake_in_json_content_is_one_error_without_a_position(
        self, _name: str, content: str, error_status: str, path: str
    ) -> None:
        response = self._check(content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        [error] = response.json()["errors"]
        assert (error["status"], error["path"], error["line"], error["column"]) == (error_status, path, None, None)

    def test_errors_from_the_whole_file_come_back_together_in_file_order(self) -> None:
        content = BASE.replace("name: Welcome\n", "name: 1.10\nname: Welcome again\ncolour: blue\n").replace(
            "duration: 1d", "duration: 3 days"
        )

        response = self._check(content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert [(e["status"], e["path"], e["line"]) for e in response.json()["errors"]] == [
            ("invalid_value", "name", 3),
            ("duplicate_key", "name", 4),
            ("unknown_field", "colour", 5),
            ("invalid_value", "steps[0].duration", 12),
        ]

    def test_a_file_with_more_errors_than_one_response_lists_says_how_many_are_left_out(self) -> None:
        content = BASE + "extra: [" + ", ".join(["!t 1"] * 60) + "]\n"

        response = self._check(content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        errors = response.json()["errors"]
        assert len(errors) == 51
        assert errors[-1]["status"] == "too_many_errors"
        assert "11 more" in errors[-1]["message"]

    @parameterized.expand(
        [
            (
                "serializer_refuses_the_step_config",
                "config: { max_wait_duration: 3 days }\n    branches: [[{ type: delay, name: Then wait, duration: 1d }]]",
            ),
            ("graph_misses_the_resolution_edge", "config: { max_wait_duration: 1d }"),
        ]
    )
    def test_a_definition_error_after_compiling_is_located_at_its_step(self, _name: str, step_body: str) -> None:
        content = BASE.replace(
            "  - type: delay\n    name: Wait a day\n    duration: 1d\n",
            f"  - type: step\n    name: Wait for a purchase\n    action_type: wait_until_condition\n    {step_body}\n",
        )

        response = self._check(content)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        [error] = response.json()["errors"]
        assert (error["status"], error["path"], error["line"]) == ("invalid_workflow", "steps[0]", 8)
        assert error["message"] and error["why"] and error["fix"]

    @patch(REPORT_USER_ACTION)
    def test_check_reports_its_outcome_as_a_usage_event(self, mock_report) -> None:
        self._check(SAMPLE)
        self._check(BASE.replace("name: Welcome\n", ""))

        checked = [c.args[2] for c in mock_report.call_args_list if c.args[1] == "hog_flow_code_checked"]
        assert [(p["result"], p["errors_count"]) for p in checked] == [("create", 0), ("invalid", 1)]

    def test_check_needs_the_workflow_read_scope(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="insights only", user=self.user, secure_value=hash_key_value(key), scopes=["insight:read"]
        )
        self.client.logout()

        response = self._check(SAMPLE, headers={"authorization": f"Bearer {key}"})

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.ee
class TestHogFlowCodeCheckObjectAccess(APIBaseTest):
    def test_check_refuses_a_caller_below_viewer_on_the_workflow_with_that_key(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        _set_up_project(self.team)
        workflow = _create_keyed_workflow(self.client, self.team, "trial-upgrade-nudge", SAMPLE_DEFINITION)
        outsider = User.objects.create_and_join(self.organization, "outsider@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=str(workflow.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=outsider, organization=self.organization),
        )
        self.client.force_login(outsider)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_check/", {"content": SAMPLE}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
