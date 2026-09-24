from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.cdp.templates.hog_function_template import sync_template_to_db
from posthog.models import Organization, ProjectSecretAPIKey, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_secret

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.workflows.backend.api.hog_flow import (
    PSAK_TRIGGER_JOB_TYPE,
    HogFlowBurstRateThrottle,
    HogFlowProjectSecretApiKeyTeamBurstThrottle,
)
from products.workflows.backend.api.test.test_hog_flow import _create_task_template
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision

webhook_template = MOCK_NODE_TEMPLATES[0]

PSAK_REFUSED = "This action does not support project secret API key access"


def _workflow(name: str = "Pushed from CI", url: str = "https://example.com/hook") -> dict:
    return {
        "name": name,
        "actions": [
            {
                "id": "trigger_node",
                "name": "trigger_1",
                "type": "trigger",
                "config": {
                    "type": "event",
                    "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}]},
                },
            },
            {
                "id": "action_1",
                "name": "action_1",
                "type": "function",
                "config": {"template_id": "template-webhook", "inputs": {"url": {"value": url}}},
            },
        ],
        "edges": [{"from": "trigger_node", "to": "action_1", "type": "continue"}],
    }


class TestHogFlowProjectSecretApiKeyAuth(APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_template_to_db(webhook_template)
        cache.clear()
        self.service = APIClient()
        self.token = self._mint_psak(self.team, ["hog_flow:write"], label="ci push key")

    def _mint_psak(self, team: Team, scopes: list[str], label: str | None = None) -> str:
        raw_token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=team,
            label=label or f"ci key {raw_token[-6:]}",
            secure_value=hash_key_value(raw_token),
            scopes=scopes,
            mask_value=f"{raw_token[:4]}...{raw_token[-4:]}",
        )
        return raw_token

    def _bearer(self, token: str) -> dict:
        return {"authorization": f"Bearer {token}"}

    def _url(self, suffix: str = "", team: Team | None = None) -> str:
        return f"/api/projects/{(team or self.team).id}/hog_flows/{suffix}"

    def _create_with_session(self) -> str:
        response = self.client.post(self._url(), _workflow())
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def _psak_audit_detail(self, flow_id: str, activity: str) -> dict:
        audit = ActivityLog.objects.get(scope="HogFlow", item_id=flow_id, activity=activity)
        assert audit.user_id is None
        assert audit.is_system is True
        assert audit.detail is not None
        assert audit.detail["trigger"]["job_type"] == PSAK_TRIGGER_JOB_TYPE
        return audit.detail

    def test_psak_create_writes_the_row_and_the_audit_row_without_a_user(self):
        response = self.service.post(self._url(), _workflow(), format="json", headers=self._bearer(self.token))

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["created_by"] is None
        flow = HogFlow.objects.get(id=response.json()["id"])
        assert flow.created_by_id is None
        assert flow.team_id == self.team.id

        detail = self._psak_audit_detail(str(flow.id), "created")
        assert detail["trigger"]["payload"] == {"label": "ci push key"}

    def test_psak_update_bumps_the_version_and_writes_the_revision_without_a_user(self):
        flow_id = self._create_with_session()

        response = self.service.patch(
            self._url(flow_id),
            {"actions": _workflow(url="https://example.com/v2")["actions"]},
            format="json",
            headers=self._bearer(self.token),
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        flow = HogFlow.objects.get(id=flow_id)
        assert flow.version == 2
        assert flow.created_by_id == self.user.id
        revision = HogFlowRevision.objects.for_team(self.team.id).get(hog_flow=flow, version=2)
        assert revision.created_by_id is None
        detail = self._psak_audit_detail(flow_id, "updated")
        assert any(change["field"] == "actions" for change in detail["changes"])

    def test_psak_create_refuses_a_create_ai_task_step_that_has_no_owner_to_run_as(self):
        sync_template_to_db(_create_task_template())
        workflow = _workflow()
        workflow["actions"][1]["config"] = {
            "template_id": "template-posthog-create-task",
            "inputs": {"prompt": {"value": "Investigate"}},
        }

        with patch("products.workflows.backend.api.hog_flow.gated_template_enabled", return_value=True):
            response = self.service.post(self._url(), workflow, format="json", headers=self._bearer(self.token))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "project secret API key" in response.json()["detail"]
        assert HogFlow.objects.count() == 0

    def test_psak_lists_and_retrieves_the_projects_workflows(self):
        flow_id = self._create_with_session()

        listed = self.service.get(self._url(), headers=self._bearer(self.token))
        fetched = self.service.get(self._url(flow_id), headers=self._bearer(self.token))

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert [row["id"] for row in listed.json()["results"]] == [flow_id]
        assert fetched.status_code == status.HTTP_200_OK, fetched.json()
        assert fetched.json()["id"] == flow_id

    @parameterized.expand(
        [
            ("read_only_key_reads_but_cannot_write", ["hog_flow:read"], status.HTTP_200_OK, status.HTTP_403_FORBIDDEN),
            ("unrelated_scope_is_refused", ["feature_flag:read"], status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_psak_scope_decides_what_the_key_may_do(self, _name, scopes, expected_list, expected_create):
        token = self._mint_psak(self.team, scopes)

        listed = self.service.get(self._url(), headers=self._bearer(token))
        created = self.service.post(self._url(), _workflow(), format="json", headers=self._bearer(token))

        assert listed.status_code == expected_list, listed.json()
        assert created.status_code == expected_create, created.json()
        assert HogFlow.objects.count() == 0

    @parameterized.expand(
        [
            ("destroy", "delete", "{id}"),
            ("bulk_delete", "post", "bulk_delete"),
            ("publish", "post", "{id}/publish"),
            ("invocations", "post", "{id}/invocations"),
            ("restore_revision", "post", "{id}/revisions/1/restore"),
        ]
    )
    def test_psak_is_refused_outside_the_push_actions(self, _name, method, path):
        flow_id = self._create_with_session()

        response = getattr(self.service, method)(
            self._url(path.format(id=flow_id)),
            {"ids": [flow_id]},
            format="json",
            headers=self._bearer(self.token),
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert response.json()["detail"] == PSAK_REFUSED
        assert HogFlow.objects.filter(id=flow_id).exists()

    def test_psak_of_another_project_cannot_read_or_write_this_projects_workflows(self):
        flow_id = self._create_with_session()
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        foreign_token = self._mint_psak(other_team, ["hog_flow:write"])

        listed = self.service.get(self._url(), headers=self._bearer(foreign_token))
        fetched = self.service.get(self._url(flow_id), headers=self._bearer(foreign_token))
        patched = self.service.patch(
            self._url(flow_id), {"name": "hijacked"}, format="json", headers=self._bearer(foreign_token)
        )
        created = self.service.post(self._url(), _workflow(), format="json", headers=self._bearer(foreign_token))

        assert listed.status_code == status.HTTP_403_FORBIDDEN, listed.json()
        assert fetched.status_code == status.HTTP_403_FORBIDDEN, fetched.json()
        assert patched.status_code == status.HTTP_403_FORBIDDEN, patched.json()
        assert created.status_code == status.HTTP_403_FORBIDDEN, created.json()
        assert HogFlow.objects.get(id=flow_id).name == "Pushed from CI"
        assert HogFlow.objects.count() == 1

    @parameterized.expand(
        [
            ("per_key", HogFlowBurstRateThrottle, False),
            ("per_project_across_keys", HogFlowProjectSecretApiKeyTeamBurstThrottle, True),
        ]
    )
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_psak_requests_are_throttled(self, _name, throttle, second_request_uses_a_new_key, _enabled):
        second_token = self._mint_psak(self.team, ["hog_flow:write"]) if second_request_uses_a_new_key else self.token

        with patch.object(throttle, "rate", "1/minute"):
            first = self.service.get(self._url(), headers=self._bearer(self.token))
            second = self.service.get(self._url(), headers=self._bearer(second_token))

        assert first.status_code == status.HTTP_200_OK, first.json()
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS, second.json()
