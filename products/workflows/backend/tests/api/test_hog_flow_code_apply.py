from copy import deepcopy
from typing import Any, Optional

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.tests.api.test_hog_flow_code_check import (
    IN_FLIGHT_COUNT,
    SAMPLE,
    SAMPLE_DEFINITION,
    _create_keyed_workflow,
    _in_flight,
    _sync_templates,
)

REPORT_USER_ACTION = "products.workflows.backend.presentation.views.hog_flow_code.report_user_action"
FIND_WORKFLOW = "products.workflows.backend.services.workflow_code.service.WorkflowCode._find_workflow"
MCP = {"x-posthog-client": "mcp"}

RENAMED_DELAY_AND_A_NEW_STEP = SAMPLE.replace("name: Wait three days", "name: Wait a few days").replace(
    "exit:\n",
    "  - type: delay\n    name: Wait before the end\n    duration: 1h\nexit:\n",
)

WEBHOOK_FILE = """\
version: 1
key: crm-sync
name: CRM sync
status: {status}
trigger:
  type: event
  event: signed up
steps:
  - type: delay
    name: Wait a day
    duration: {duration}
  - type: function
    id: tell_the_crm
    name: Tell the CRM
    template: template-webhook
    inputs:
      url: https://example.com/hooks/{path}
"""


def _webhook_file(status: str = "draft", duration: str = "1d", path: str = "signup") -> str:
    return WEBHOOK_FILE.format(status=status, duration=duration, path=path)


class TestHogFlowCodeApply(APIBaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        _sync_templates()

    def _apply(self, content: str, headers: Optional[dict[str, str]] = None) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_apply/",
            {"content": content},
            format="json",
            headers=headers or {},
        )

    def _applied(self, content: str, expected_status: int = status.HTTP_200_OK, **kwargs: Any) -> dict[str, Any]:
        response = self._apply(content, **kwargs)
        assert response.status_code == expected_status, response.json()
        return response.json()

    def _check_url(self) -> str:
        return f"/api/projects/{self.team.id}/hog_flows/code_check/"

    def _workflow(self, key: str) -> HogFlow:
        return HogFlow.objects.get(team=self.team, key=key)

    def _revision_count(self, workflow: HogFlow) -> int:
        return HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow=workflow).count()

    def _stage_draft(self, workflow: HogFlow, draft_encrypted_inputs: Optional[dict[str, Any]] = None) -> None:
        workflow.refresh_from_db()
        draft = {
            "actions": [
                {**action, "name": "Wait a week"} if action["id"] == "wait_a_day" else action
                for action in deepcopy(workflow.actions)
            ],
            "edges": workflow.edges,
            "variables": workflow.variables or [],
            "exit_condition": workflow.exit_condition,
            "trigger": workflow.trigger,
        }
        HogFlow.objects.filter(id=workflow.id).update(draft=draft, draft_encrypted_inputs=draft_encrypted_inputs)

    def test_apply_of_a_new_key_creates_a_draft_workflow_with_the_compiled_graph(self) -> None:
        body = self._applied(SAMPLE, status.HTTP_201_CREATED)

        assert body["result"] == "created"
        assert body["plan"]["result"] == "create"
        workflow = self._workflow("trial-upgrade-nudge")
        assert body["workflow"] == {
            "id": str(workflow.id),
            "key": "trial-upgrade-nudge",
            "name": "Trial upgrade nudge",
            "version": workflow.version,
            "status": "draft",
        }
        assert workflow.status == HogFlow.State.DRAFT
        assert workflow.created_by == self.user
        assert [a["id"] for a in workflow.actions] == [a["id"] for a in SAMPLE_DEFINITION["actions"]]
        assert workflow.edges == SAMPLE_DEFINITION["edges"]

    def test_applying_the_same_file_again_writes_nothing(self) -> None:
        self._applied(SAMPLE, status.HTTP_201_CREATED)
        workflow = self._workflow("trial-upgrade-nudge")
        revisions_before = self._revision_count(workflow)
        activity_before = ActivityLog.objects.filter(scope="HogFlow", item_id=str(workflow.id)).count()

        body = self._applied(SAMPLE)

        assert body["result"] == "unchanged"
        after = self._workflow("trial-upgrade-nudge")
        assert (after.version, after.updated_at) == (workflow.version, workflow.updated_at)
        assert self._revision_count(workflow) == revisions_before
        assert ActivityLog.objects.filter(scope="HogFlow", item_id=str(workflow.id)).count() == activity_before

    @patch(IN_FLIGHT_COUNT)
    def test_apply_of_a_renamed_step_updates_the_workflow_and_moves_its_people_as_planned(self, mock_count) -> None:
        workflow = _create_keyed_workflow(self.client, self.team, "trial-upgrade-nudge", SAMPLE_DEFINITION)
        mock_count.return_value = _in_flight({"wait_three_days": 41})

        body = self._applied(RENAMED_DELAY_AND_A_NEW_STEP)

        assert body["result"] == "updated"
        [removed] = body["plan"]["removed_steps"]
        assert (removed["action_id"], removed["runs"], removed["moves_to"]["action_id"]) == (
            "wait_three_days",
            41,
            "which_plan",
        )
        assert [step["id"] for step in body["plan"]["added_steps"]] == ["wait_a_few_days", "wait_before_the_end"]
        after = self._workflow("trial-upgrade-nudge")
        assert after.version == workflow.version + 1
        assert body["workflow"]["version"] == after.version
        assert after.action_redirects == {"wait_three_days": removed["moves_to"]["action_id"]}
        assert "wait_three_days" not in [a["id"] for a in after.actions]
        assert HogFlowRevision.objects.for_team(self.team.id).filter(hog_flow=after, version=after.version).exists()
        assert ActivityLog.objects.filter(scope="HogFlow", item_id=str(after.id), activity="updated").exists()

    @patch(REPORT_USER_ACTION)
    def test_apply_reports_what_it_did_as_a_usage_event(self, mock_report) -> None:
        self._applied(SAMPLE, status.HTTP_201_CREATED)
        self._applied(SAMPLE)
        self._applied(RENAMED_DELAY_AND_A_NEW_STEP)

        applied = [c.args[2] for c in mock_report.call_args_list if c.args[1] == "hog_flow_code_applied"]
        assert [(p["result"], p["added_steps"], p["removed_steps"]) for p in applied] == [
            ("created", 4, 0),
            ("unchanged", 0, 0),
            ("updated", 2, 1),
        ]

    def test_apply_to_a_workflow_with_a_staged_draft_writes_live_and_clears_the_draft(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        workflow = self._workflow("crm-sync")
        HogFlow.objects.filter(id=workflow.id).update(status=HogFlow.State.ACTIVE)
        self._stage_draft(workflow)

        body = self._applied(_webhook_file(status="active", duration="2d"))

        assert body["result"] == "updated"
        assert body["plan"]["discards_draft"] is True
        after = self._workflow("crm-sync")
        assert (after.draft, after.draft_updated_at, after.draft_encrypted_inputs) == (None, None, None)
        assert next(a for a in after.actions if a["id"] == "wait_a_day")["config"]["delay_duration"] == "2d"

    def test_apply_over_a_staged_draft_keeps_the_live_secret_not_the_drafts(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        workflow = self._workflow("crm-sync")
        live_secret = {"value": "live-secret-not-real"}
        HogFlow.objects.filter(id=workflow.id).update(
            encrypted_inputs={"tell_the_crm": {"signing_secret": live_secret}}
        )
        self._stage_draft(
            workflow, draft_encrypted_inputs={"tell_the_crm": {"signing_secret": {"value": "draft-secret-not-real"}}}
        )

        self._applied(_webhook_file(path="changed"))

        after = self._workflow("crm-sync")
        assert after.encrypted_inputs["tell_the_crm"]["signing_secret"]["value"] == live_secret["value"]
        assert after.draft_encrypted_inputs is None

    def test_a_file_with_errors_gets_the_errors_check_gives_and_writes_nothing(self) -> None:
        broken = _webhook_file(duration="3 days").replace("name: CRM sync", "name: 1.10")

        response = self._apply(broken)
        checked = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_check/", {"content": broken}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == checked.json()
        assert len(response.json()["errors"]) == 2
        assert not HogFlow.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("creates_an_active_workflow", None, _webhook_file(status="active"), status.HTTP_201_CREATED),
            ("activates_a_draft_workflow", HogFlow.State.DRAFT, _webhook_file(status="active"), status.HTTP_200_OK),
            ("disables_an_active_workflow", HogFlow.State.ACTIVE, _webhook_file(status="draft"), status.HTTP_200_OK),
        ]
    )
    def test_a_status_change_through_mcp_is_refused_and_allowed_through_the_api(
        self, _name: str, stored_status: Optional[str], content: str, api_status: int
    ) -> None:
        if stored_status is not None:
            self._applied(_webhook_file(), status.HTTP_201_CREATED)
            HogFlow.objects.filter(team=self.team, key="crm-sync").update(status=stored_status)

        refused = self._applied(content, status.HTTP_400_BAD_REQUEST, headers=MCP)
        checked = self.client.post(self._check_url(), {"content": content}, format="json", headers=MCP)

        [error] = refused["errors"]
        assert (error["status"], error["path"], error["line"]) == ("status_change_not_allowed", "status", 4)
        assert "workflows-enable" in error["fix"]
        assert checked.json() == refused
        assert HogFlow.objects.filter(team=self.team, key="crm-sync").count() == (stored_status is not None)
        assert self._apply(content).status_code == api_status

    def test_a_content_change_to_an_active_workflow_through_mcp_is_staged_for_publish(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        HogFlow.objects.filter(team=self.team, key="crm-sync").update(status=HogFlow.State.ACTIVE)
        live = self._workflow("crm-sync")
        checked = self.client.post(
            self._check_url(), {"content": _webhook_file(status="active", duration="2d")}, format="json", headers=MCP
        )

        body = self._applied(_webhook_file(status="active", duration="2d"), headers=MCP)

        assert checked.json()["plan"] == body["plan"]
        assert body["result"] == "staged"
        assert body["plan"]["result"] == "stage"
        assert body["plan"]["discards_draft"] is False
        staged = self._workflow("crm-sync")
        assert (staged.actions, staged.version) == (live.actions, live.version)
        assert (
            next(a for a in (staged.draft or {})["actions"] if a["id"] == "wait_a_day")["config"]["delay_duration"]
            == "2d"
        )

        preview = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{live.id}/publish/", {"confirm": False}, format="json"
        )
        published = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/{live.id}/publish/",
            {"confirm": True, "confirm_token": preview.json()["confirm_token"]},
            format="json",
        )

        assert published.status_code == status.HTTP_200_OK, published.json()
        after = self._workflow("crm-sync")
        assert next(a for a in after.actions if a["id"] == "wait_a_day")["config"]["delay_duration"] == "2d"
        assert self._applied(_webhook_file(status="active", duration="2d"), headers=MCP)["result"] == "unchanged"

    @patch(IN_FLIGHT_COUNT)
    def test_a_write_that_lands_before_the_lock_is_planned_against_not_overwritten_blind(self, mock_count) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        workflow = self._workflow("crm-sync")

        def concurrent_edit(**_kwargs: Any) -> MagicMock:
            actions = [
                {**action, "config": {"delay_duration": "5d"}} if action["id"] == "wait_a_day" else action
                for action in workflow.actions
            ]
            HogFlow.objects.filter(id=workflow.id).update(actions=actions, version=workflow.version + 1)
            return _in_flight({})

        mock_count.side_effect = concurrent_edit

        body = self._applied(_webhook_file(path="changed"))

        assert body["result"] == "updated"
        assert {step["id"] for step in body["plan"]["changed_steps"]} == {"wait_a_day", "tell_the_crm"}
        after = self._workflow("crm-sync")
        assert after.version == workflow.version + 2
        assert next(a for a in after.actions if a["id"] == "wait_a_day")["config"]["delay_duration"] == "1d"

    def test_a_concurrent_create_of_the_same_key_is_a_conflict(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)

        with patch(FIND_WORKFLOW, return_value=None):
            body = self._applied(_webhook_file(duration="2d"), status.HTTP_409_CONFLICT)

        [error] = body["errors"]
        assert error["status"] == "conflict"
        assert "again" in error["fix"]
        assert HogFlow.objects.filter(team=self.team, key="crm-sync").count() == 1

    def test_fields_the_file_does_not_carry_keep_their_stored_values(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        stored = {
            "conversion": {"window_minutes": 60, "filters": []},
            "trigger_masking": {"ttl": 600, "hash": "{person.id}", "threshold": 1},
            "email_sending_rate_limit": {"per_second": 5},
            "abort_action": "exit_node",
        }
        HogFlow.objects.filter(team=self.team, key="crm-sync").update(**stored)

        assert self._applied(_webhook_file(duration="2d"))["result"] == "updated"

        after = self._workflow("crm-sync")
        assert {field: getattr(after, field) for field in stored} == stored

    def test_a_request_with_more_than_the_file_is_refused(self) -> None:
        self._applied(_webhook_file(), status.HTTP_201_CREATED)
        HogFlow.objects.filter(team=self.team, key="crm-sync").update(status=HogFlow.State.ACTIVE)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_apply/",
            {"content": _webhook_file(status="active", duration="2d"), "stage_draft": True},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "stage_draft" in str(response.json())
        after = self._workflow("crm-sync")
        assert next(a for a in after.actions if a["id"] == "wait_a_day")["config"]["delay_duration"] == "1d"

    def test_apply_needs_the_workflow_write_scope(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only", user=self.user, secure_value=hash_key_value(key), scopes=["hog_flow:read"]
        )
        self.client.logout()

        response = self._apply(SAMPLE, headers={"authorization": f"Bearer {key}"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not HogFlow.objects.filter(team=self.team).exists()


@pytest.mark.ee
class TestHogFlowCodeApplyObjectAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        _sync_templates()
        self.workflow = _create_keyed_workflow(self.client, self.team, "trial-upgrade-nudge", SAMPLE_DEFINITION)
        self.member = User.objects.create_and_join(self.organization, "member@example.com", "testtest")

    def _grant(self, access_level: str, resource_id: Optional[str]) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource="hog_flow",
            resource_id=resource_id,
            access_level=access_level,
            organization_member=OrganizationMembership.objects.get(user=self.member, organization=self.organization),
        )

    def test_apply_refuses_a_caller_below_editor_on_the_workflow_with_that_key(self) -> None:
        self._grant("viewer", str(self.workflow.id))
        self.client.force_login(self.member)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_apply/",
            {"content": SAMPLE.replace("duration: 3d", "duration: 4d")},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.workflow.refresh_from_db()
        delays = {a["id"]: a["config"].get("delay_duration") for a in self.workflow.actions}
        assert delays["wait_three_days"] == "3d"

    def test_apply_refuses_a_new_key_to_a_caller_who_edits_only_one_workflow(self) -> None:
        self._grant("viewer", None)
        self._grant("editor", str(self.workflow.id))
        self.client.force_login(self.member)

        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_apply/",
            {"content": _webhook_file()},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not HogFlow.objects.filter(team=self.team, key="crm-sync").exists()
