from copy import deepcopy
from datetime import timedelta

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

    @patch("products.workflows.backend.presentation.views.hog_flow.create_hog_flow_invocation_test")
    def test_live_draft_invocation_requires_cohort_edit_access(self, invoke: MagicMock) -> None:
        trigger = self._flow()["actions"][0]
        exit_action = self._flow()["actions"][2]
        workflow = HogFlow.objects.create(
            team=self.team,
            name="Existing workflow",
            status=HogFlow.State.ACTIVE,
            actions=[trigger, exit_action],
            edges=[{"from": "trigger", "to": "exit", "type": "continue"}],
            trigger=trigger["config"],
            draft={"actions": self._flow()["actions"], "edges": self._flow()["edges"], "trigger": trigger["config"]},
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save(update_fields=["level"])
        AccessControl.objects.create(team=self.team, resource="cohort", access_level="none")

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
