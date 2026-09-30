from copy import deepcopy
from typing import Any, Optional

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.tests.api.test_hog_flow_code_check import (
    SAMPLE_DEFINITION,
    _create_keyed_workflow,
    _sync_templates,
)

REPORT_USER_ACTION = "products.workflows.backend.presentation.views.hog_flow_code.report_user_action"

WEBHOOK_WITH_SECRET = {
    "id": "tell_the_crm",
    "name": "Tell the CRM",
    "description": "",
    "type": "function",
    "config": {
        "template_id": "template-webhook",
        "inputs": {
            "url": {"value": "https://example.com/hooks/trial"},
            "signing_secret": {"value": "not-a-real-secret"},
        },
    },
}


def _editor_built(definition: dict[str, Any]) -> dict[str, Any]:
    built = deepcopy(definition)
    built["actions"] = [
        {**action, "created_at": 1700000000000, "updated_at": 1700000000000, "on_error": None, "filters": None}
        for action in built["actions"]
    ]
    built["edges"] = list(reversed(built["edges"]))
    return built


def _with_secret_webhook(definition: dict[str, Any]) -> dict[str, Any]:
    changed = deepcopy(definition)
    changed["actions"] = [WEBHOOK_WITH_SECRET if a["id"] == "tell_the_crm" else a for a in changed["actions"]]
    return changed


class TestHogFlowCodePull(APIBaseTest):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        _sync_templates()

    def _pull(self, workflow: HogFlow, team: Optional[Team] = None, **kwargs: Any) -> Any:
        return self.client.get(f"/api/projects/{(team or self.team).id}/hog_flows/{workflow.id}/code/", **kwargs)

    def _check(self, content: str) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/code_check/", {"content": content}, format="json"
        )

    def _create_unkeyed(self, definition: dict[str, Any]) -> HogFlow:
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", definition, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return HogFlow.objects.get(id=response.json()["id"])

    @patch(REPORT_USER_ACTION)
    def test_a_workflow_built_in_the_editor_comes_back_as_a_file_check_reads_as_unchanged(self, mock_report) -> None:
        workflow = _create_keyed_workflow(
            self.client, self.team, "trial-upgrade-nudge", _editor_built(SAMPLE_DEFINITION)
        )

        response = self._pull(workflow)

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["content"].startswith("version: 1\nkey: trial-upgrade-nudge\n")
        assert body["warnings"] == []
        checked = self._check(body["content"])
        assert checked.status_code == status.HTTP_200_OK, checked.json()
        assert checked.json()["plan"]["result"] == "unchanged", checked.json()["plan"]
        [pulled] = [c.args[2] for c in mock_report.call_args_list if c.args[1] == "hog_flow_code_pulled"]
        assert (pulled["workflow_id"], pulled["warnings_count"]) == (str(workflow.id), 0)

    @parameterized.expand(
        [
            ("secret_input", "signing_secret"),
            ("no_key", "no key"),
            ("staged_draft", "staged draft"),
            ("email_design_edited", "design"),
        ]
    )
    def test_what_the_file_cannot_carry_comes_back_as_a_warning(self, case: str, named: str) -> None:
        definition = _with_secret_webhook(SAMPLE_DEFINITION) if case == "secret_input" else SAMPLE_DEFINITION
        if case == "no_key":
            workflow = self._create_unkeyed(definition)
        else:
            workflow = _create_keyed_workflow(self.client, self.team, "trial-upgrade-nudge", definition)
        if case == "staged_draft":
            HogFlow.objects.filter(id=workflow.id).update(draft={"actions": workflow.actions, "edges": workflow.edges})
        if case == "email_design_edited":
            actions = deepcopy(workflow.actions)
            email = next(a for a in actions if a["id"] == "thank_the_new_customer")
            email["config"]["inputs"]["email"]["value"]["design"] = {"body": {"rows": []}, "counters": {}}
            HogFlow.objects.filter(id=workflow.id).update(actions=actions)

        response = self._pull(workflow)

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        matching = [w for w in body["warnings"] if named in w["message"]]
        assert len(matching) == 1, body["warnings"]
        assert f"# {matching[0]['message']}" in body["content"]
        assert "not-a-real-secret" not in body["content"]
        assert self._check(body["content"]).status_code == status.HTTP_200_OK

    def test_a_workflow_in_another_project_is_not_found(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        workflow = _create_keyed_workflow(self.client, other_team, "trial-upgrade-nudge", SAMPLE_DEFINITION)

        response = self._pull(workflow)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_pull_needs_the_workflow_read_scope(self) -> None:
        workflow = _create_keyed_workflow(self.client, self.team, "trial-upgrade-nudge", SAMPLE_DEFINITION)
        key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="insights only", user=self.user, secure_value=hash_key_value(key), scopes=["insight:read"]
        )
        self.client.logout()

        response = self._pull(workflow, headers={"authorization": f"Bearer {key}"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
