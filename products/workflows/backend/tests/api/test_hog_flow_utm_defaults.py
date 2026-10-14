from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from products.cdp.backend.templates.hog_function_template import sync_template_to_db
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.tests.api.test_hog_flow import _email_function_template, _valid_email_inputs

TRIGGER = {
    "id": "trigger_node",
    "name": "trigger",
    "type": "trigger",
    "config": {"type": "event", "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events"}]}},
}


def _email_action(**config: Any) -> dict[str, Any]:
    return {
        "id": "email_1",
        "name": "Send email",
        "type": "function_email",
        "config": {"template_id": "template-email", "inputs": _valid_email_inputs(), **config},
    }


class TestHogFlowUtmDefaults(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        sync_template_to_db(_email_function_template())
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={"email_utm_tags_enabled": True, "email_utm_params": {"utm_source": "newsletter"}},
        )

    def _email_config(self, flow: HogFlow) -> dict[str, Any]:
        flow.refresh_from_db()
        return next(a for a in flow.actions if a["type"] == "function_email")["config"]

    @parameterized.expand(
        [
            ("no choice made copies the team defaults", {}, True, {"utm_source": "newsletter"}),
            ("an explicit choice is kept", {"utm_tags_enabled": False}, False, None),
            (
                "values the caller supplied are kept",
                {"utm_params": {"utm_source": "partner"}},
                True,
                {"utm_source": "partner"},
            ),
        ]
    )
    def test_create_copies_team_defaults_into_new_email_steps(
        self, _name: str, email_config: dict, expected_on: bool, expected_params: dict | None
    ) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "New flow", "actions": [TRIGGER, _email_action(**email_config)]},
            format="json",
        )

        assert response.status_code == 201, response.json()
        config = self._email_config(HogFlow.objects.get(pk=response.json()["id"]))
        assert config["utm_tags_enabled"] is expected_on
        assert config.get("utm_params") == expected_params
