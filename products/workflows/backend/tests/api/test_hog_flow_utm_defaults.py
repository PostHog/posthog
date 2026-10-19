from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

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

    def test_test_invocation_leaves_existing_steps_without_team_defaults(self) -> None:
        created = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows",
            {"name": "Old flow", "actions": [TRIGGER, _email_action(utm_tags_enabled=False)]},
            format="json",
        )
        assert created.status_code == 201, created.json()
        flow = HogFlow.objects.get(pk=created.json()["id"])
        # A step saved before team defaults existed carries no UTM settings.
        flow.actions = [
            {**a, "config": {k: v for k, v in a["config"].items() if not k.startswith("utm_")}} for a in flow.actions
        ]
        flow.save()

        with patch(
            "products.workflows.backend.presentation.views.hog_flow.create_hog_flow_invocation_test"
        ) as mock_invoke:
            mock_invoke.return_value = MagicMock(status_code=200, json=lambda: {"status": "success"})
            response = self.client.post(
                f"/api/projects/{self.team.id}/hog_flows/{flow.id}/invocations/",
                {
                    "configuration": {"name": "Old flow", "actions": [TRIGGER, _email_action()]},
                    "globals": {"event": {"event": "$pageview", "distinct_id": "test-distinct-id"}},
                },
                format="json",
            )

        assert response.status_code == 200, response.json()
        actions = mock_invoke.call_args.kwargs["payload"]["configuration"]["actions"]
        email_config = next(a for a in actions if a["type"] == "function_email")["config"]
        assert "utm_tags_enabled" not in email_config
        assert "utm_params" not in email_config

    @parameterized.expand([("staging the draft", True), ("publishing", False)])
    def test_an_email_step_only_in_the_staged_draft_is_not_seeded(self, _name: str, stage_draft: bool) -> None:
        # The step was staged before the team turned on defaults, so it carries no UTM settings.
        email = _email_action()
        flow = HogFlow.objects.create(
            team=self.team,
            name="Live flow",
            status=HogFlow.State.ACTIVE,
            created_by=self.user,
            actions=[TRIGGER],
            draft={"actions": [TRIGGER, email]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{flow.id}",
            {"actions": [TRIGGER, email], **({"stage_draft": True} if stage_draft else {})},
            format="json",
        )

        assert response.status_code == 200, response.json()
        flow.refresh_from_db()
        saved = ((flow.draft or {}).get("actions") if stage_draft else flow.actions) or []
        email_config = next(a for a in saved if a["type"] == "function_email")["config"]
        assert "utm_tags_enabled" not in email_config
        assert "utm_params" not in email_config
