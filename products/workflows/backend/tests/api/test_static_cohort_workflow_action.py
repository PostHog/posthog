import json
from copy import deepcopy
from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models import HogFlow

TEMPLATE_ID = "template-posthog-add-person-to-static-cohort"


def _template() -> dict:
    template = deepcopy(MOCK_NODE_TEMPLATES[0])
    template.update(
        {
            "id": TEMPLATE_ID,
            "name": "Add person to static cohort",
            "status": "hidden",
            "inputs_schema": [
                {
                    "key": "cohort_id",
                    "type": "number",
                    "label": "Static cohort",
                    "required": True,
                    "secret": False,
                    "hidden": False,
                }
            ],
        }
    )
    return template


class TestStaticCohortWorkflowAction(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(_template())
        self.cohort = Cohort.objects.create(team=self.team, name="Contacted", is_static=True)
        self.url = f"/api/projects/{self.team.id}/hog_flows"

    def _flow(self, cohort_id: int | None = None, trigger_type: str = "event") -> dict:
        trigger_config: dict = {"type": trigger_type}
        if trigger_type == "event":
            trigger_config["filters"] = {"events": [{"id": "$pageview", "name": "$pageview", "type": "events"}]}
        elif trigger_type == "batch":
            trigger_config["filters"] = {"audience_type": "persons", "properties": []}
        elif trigger_type in {"data-warehouse-table", "data-warehouse-view"}:
            trigger_config.update({"table_name": "source.rows", "filters": {"properties": []}})
        return {
            "name": "Contact follow-up",
            "status": "active",
            "actions": [
                {"id": "trigger", "name": "Trigger", "type": "trigger", "config": trigger_config},
                {
                    "id": "cohort",
                    "name": "Mark contacted",
                    "type": "function",
                    "config": {
                        "template_id": TEMPLATE_ID,
                        "inputs": {"cohort_id": {"value": cohort_id if cohort_id is not None else self.cohort.id}},
                    },
                },
                {"id": "exit", "name": "Exit", "type": "exit", "config": {"reason": "Workflow completed"}},
            ],
            "edges": [
                {"from": "trigger", "to": "cohort", "type": "continue"},
                {"from": "cohort", "to": "exit", "type": "continue"},
            ],
        }

    def _deny_cohort_edit_access(self) -> None:
        self._enable_member_access_control()
        AccessControl.objects.create(team=self.team, resource="cohort", access_level="none")

    def _deny_selected_cohort_edit_access(self) -> None:
        self._enable_member_access_control()
        AccessControl.objects.create(
            team=self.team,
            resource="cohort",
            resource_id=str(self.cohort.id),
            access_level="none",
        )

    def _enable_member_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.uses_most_specific_access_resolution = True
        self.organization.save(update_fields=["available_product_features", "uses_most_specific_access_resolution"])
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save(update_fields=["level"])

    def _active_workflow_with_static_cohort_draft(self) -> HogFlow:
        flow = self._flow()
        trigger = flow["actions"][0]
        exit_action = flow["actions"][2]
        return HogFlow.objects.create(
            team=self.team,
            name="Existing workflow",
            status=HogFlow.State.ACTIVE,
            actions=[trigger, exit_action],
            edges=[{"from": "trigger", "to": "exit", "type": "continue"}],
            trigger=trigger["config"],
            draft={"actions": flow["actions"], "edges": flow["edges"], "trigger": trigger["config"]},
        )

    def _set_draft_cohort_input(self, workflow: HogFlow, cohort_id_input: dict) -> None:
        draft = deepcopy(workflow.draft)
        cohort_action = next(action for action in draft["actions"] if action["id"] == "cohort")
        cohort_action["config"]["inputs"]["cohort_id"] = cohort_id_input
        workflow.draft = draft
        workflow.save(update_fields=["draft"])

    def test_static_cohort_action_round_trips(self) -> None:
        response = self.client.post(self.url, self._flow(), format="json")

        assert response.status_code == 201, response.json()
        action = response.json()["actions"][1]
        assert action["config"]["template_id"] == TEMPLATE_ID
        assert action["config"]["inputs"]["cohort_id"]["value"] == self.cohort.id

    def test_rejects_dynamic_deleted_and_missing_cohorts(self) -> None:
        dynamic = Cohort.objects.create(team=self.team, name="Dynamic", is_static=False)
        deleted = Cohort.objects.create(team=self.team, name="Deleted", is_static=True, deleted=True)

        responses = [
            self.client.post(self.url, self._flow(dynamic.id), format="json"),
            self.client.post(self.url, self._flow(deleted.id), format="json"),
            self.client.post(self.url, self._flow(999999), format="json"),
        ]

        assert [response.status_code for response in responses] == [400, 400, 400]

    def test_graph_update_rejects_a_dynamic_cohort(self) -> None:
        create = self.client.post(self.url, {**self._flow(), "status": "draft"}, format="json")
        assert create.status_code == 201, create.json()
        dynamic = Cohort.objects.create(team=self.team, name="Dynamic", is_static=False)

        response = self.client.patch(
            f"{self.url}/{create.json()['id']}/graph",
            {
                "operations": [
                    {
                        "op": "update_action",
                        "id": "cohort",
                        "patch": {
                            "config": {
                                "template_id": TEMPLATE_ID,
                                "inputs": {"cohort_id": {"value": dynamic.id}},
                            }
                        },
                    }
                ]
            },
            format="json",
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        assert response.status_code == 400, response.json()
        assert "Select a static cohort" in str(response.json())

    @parameterized.expand(["data-warehouse-table", "schedule"])
    def test_rejects_a_person_less_trigger(self, trigger_type: str) -> None:
        response = self.client.post(self.url, self._flow(trigger_type=trigger_type), format="json")

        assert response.status_code == 400, response.json()
        assert TEMPLATE_ID in response.json()["detail"]

    def test_personal_api_key_requires_cohort_write(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="workflow writer",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write"],
        )

        response = self.client.post(
            self.url,
            self._flow(),
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 403, response.json()
        assert "cohort:write" in response.json()["detail"]

    def test_form_encoded_action_requires_cohort_write(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="workflow writer",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write"],
        )
        flow = self._flow()
        payload: dict[str, str] = {"name": flow["name"], "status": flow["status"]}
        for index, action in enumerate(flow["actions"]):
            payload[f"actions[{index}]id"] = action["id"]
            payload[f"actions[{index}]name"] = action["name"]
            payload[f"actions[{index}]type"] = action["type"]
            payload[f"actions[{index}]config"] = json.dumps(action["config"])
        for index, edge in enumerate(flow["edges"]):
            payload[f"edges[{index}]from"] = edge["from"]
            payload[f"edges[{index}]to"] = edge["to"]
            payload[f"edges[{index}]type"] = edge["type"]

        response = self.client.post(
            self.url,
            payload,
            format="multipart",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 403, response.json()
        assert "cohort:write" in response.json()["detail"]

    def test_personal_api_key_with_cohort_write_can_save(self) -> None:
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="workflow and cohort writer",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write", "cohort:write"],
        )

        response = self.client.post(
            self.url,
            self._flow(),
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 201, response.json()

    def test_personal_api_key_requires_cohort_write_for_rerun(self) -> None:
        create = self.client.post(self.url, self._flow(), format="json")
        assert create.status_code == 201, create.json()
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="workflow runner",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write", "person:read", "group:read"],
        )

        response = self.client.post(
            f"{self.url}/{create.json()['id']}/rerun",
            {},
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 403, response.json()
        assert "cohort:write" in response.json()["detail"]

    @time_machine.travel("2026-10-19T00:00:00Z", tick=False)
    def test_personal_api_key_requires_cohort_write_for_schedule_updates(self) -> None:
        create = self.client.post(self.url, self._flow(trigger_type="batch"), format="json")
        assert create.status_code == 201, create.json()
        scheduled = self.client.post(
            f"{self.url}/{create.json()['id']}/schedules",
            {
                "rrule": "FREQ=DAILY;INTERVAL=1",
                "starts_at": (timezone.now() + timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        assert scheduled.status_code == 201, scheduled.json()
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="workflow scheduler",
            user=self.user,
            secure_value=hash_key_value(key),
            scopes=["hog_flow:write"],
        )

        response = self.client.patch(
            f"{self.url}/{create.json()['id']}/schedules/{scheduled.json()['id']}",
            {"variables": {"source": "review"}},
            format="json",
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 403, response.json()
        assert "cohort:write" in response.json()["detail"]

    def test_publish_requires_cohort_edit_access(self) -> None:
        workflow = self._active_workflow_with_static_cohort_draft()
        self._deny_cohort_edit_access()
        preview = self.client.post(f"{self.url}/{workflow.id}/publish", {}, format="json")
        assert preview.status_code == 200, preview.json()

        response = self.client.post(
            f"{self.url}/{workflow.id}/publish",
            {
                "confirm": True,
                "confirm_token": preview.json()["confirm_token"],
                "stage_draft": True,
            },
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "access to edit cohorts" in str(response.json())
        workflow.refresh_from_db()
        assert workflow.draft is not None

    @parameterized.expand(
        [
            (
                "rerun",
                "rerun",
                {"filter": {"window_start": "2026-10-13T00:00:00Z", "window_end": "2026-10-14T00:00:00Z"}},
                "rerun_hog_invocations",
            ),
            ("batch", "batch_jobs", {}, "create_batch_job"),
            (
                "schedule",
                "schedules",
                {"rrule": "FREQ=DAILY;INTERVAL=1"},
                "create_schedule",
            ),
        ]
    )
    @time_machine.travel("2026-10-19T00:00:00Z", tick=False)
    def test_live_execution_requires_cohort_edit_access(
        self, _name: str, path: str, payload: dict, enqueue_function: str
    ) -> None:
        create = self.client.post(self.url, self._flow(trigger_type="batch"), format="json")
        assert create.status_code == 201, create.json()
        self._deny_cohort_edit_access()
        if path == "schedules":
            payload = {**payload, "starts_at": (timezone.now() + timedelta(days=1)).isoformat()}

        with patch(f"products.workflows.backend.presentation.views.hog_flow.{enqueue_function}") as enqueue:
            response = self.client.post(f"{self.url}/{create.json()['id']}/{path}", payload, format="json")

        assert response.status_code == 403, response.json()
        assert "access to edit cohorts" in response.json()["detail"]
        enqueue.assert_not_called()

    def test_save_requires_edit_access_to_selected_cohort(self) -> None:
        self._deny_selected_cohort_edit_access()

        response = self.client.post(self.url, self._flow(), format="json")

        assert response.status_code == 400, response.json()
        assert "access to edit cohorts" in str(response.json())

    @patch("products.workflows.backend.presentation.views.hog_flow.create_batch_job")
    def test_live_execution_requires_edit_access_to_selected_cohort(self, create_batch_job: MagicMock) -> None:
        self._enable_member_access_control()
        create = self.client.post(self.url, self._flow(trigger_type="batch"), format="json")
        assert create.status_code == 201, create.json()
        AccessControl.objects.create(
            team=self.team,
            resource="cohort",
            resource_id=str(self.cohort.id),
            access_level="none",
        )

        response = self.client.post(f"{self.url}/{create.json()['id']}/batch_jobs", {}, format="json")

        assert response.status_code == 403, response.json()
        assert "selected cohort" in response.json()["detail"]
        create_batch_job.assert_not_called()

    @patch("products.workflows.backend.presentation.views.hog_flow.create_hog_flow_invocation_test")
    def test_live_draft_invocation_requires_cohort_edit_access(self, invoke: MagicMock) -> None:
        workflow = self._active_workflow_with_static_cohort_draft()
        self._deny_cohort_edit_access()

        response = self.client.post(
            f"{self.url}/{workflow.id}/invocations",
            {
                "use_draft": True,
                "mock_async_functions": False,
                "globals": {"event": {"event": "$pageview", "properties": {}}},
            },
            format="json",
        )

        assert response.status_code == 403, response.json()
        invoke.assert_not_called()

    @parameterized.expand([("float", float), ("string", str)])
    @patch("products.workflows.backend.presentation.views.hog_flow.create_hog_flow_invocation_test")
    def test_live_draft_invocation_rejects_a_non_integer_cohort_id(
        self, _name: str, cohort_id_type: type, invoke: MagicMock
    ) -> None:
        workflow = self._active_workflow_with_static_cohort_draft()
        self._set_draft_cohort_input(workflow, {"value": cohort_id_type(self.cohort.id)})
        self._deny_selected_cohort_edit_access()

        response = self.client.post(
            f"{self.url}/{workflow.id}/invocations",
            {
                "use_draft": True,
                "mock_async_functions": False,
                "globals": {"event": {"event": "$pageview", "properties": {}}},
            },
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "Select a static cohort" in str(response.json())
        invoke.assert_not_called()

    @patch("products.workflows.backend.presentation.views.hog_flow.create_hog_flow_invocation_test")
    def test_live_draft_invocation_strips_executable_cohort_input_metadata(self, invoke: MagicMock) -> None:
        restricted_cohort = Cohort.objects.create(team=self.team, name="Restricted", is_static=True)
        self._enable_member_access_control()
        AccessControl.objects.create(
            team=self.team,
            resource="cohort",
            resource_id=str(restricted_cohort.id),
            access_level="none",
        )
        workflow = self._active_workflow_with_static_cohort_draft()
        self._set_draft_cohort_input(
            workflow,
            {
                "value": self.cohort.id,
                "bytecode": ["_H", 1, 32, restricted_cohort.id],
                "bytecode_contract": "client-supplied",
                "templating": "hog",
                "transpiled": str(restricted_cohort.id),
            },
        )
        invoke.return_value.status_code = 200
        invoke.return_value.json.return_value = {"status": "success"}

        response = self.client.post(
            f"{self.url}/{workflow.id}/invocations",
            {
                "use_draft": True,
                "mock_async_functions": False,
                "globals": {"event": {"event": "$pageview", "properties": {}}},
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        actions = invoke.call_args.kwargs["payload"]["configuration"]["actions"]
        cohort_action = next(action for action in actions if action["id"] == "cohort")
        assert cohort_action["config"]["inputs"]["cohort_id"] == {"value": self.cohort.id}
