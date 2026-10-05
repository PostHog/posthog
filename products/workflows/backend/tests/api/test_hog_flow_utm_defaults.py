from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.cdp.templates.hog_function_template import sync_template_to_db

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

    def _flow(self, name: str, status: str, origin_product: str | None = None, **email_config: Any) -> HogFlow:
        return HogFlow.objects.create(
            team=self.team,
            name=name,
            status=status,
            origin_product=origin_product,
            actions=[TRIGGER, _email_action(**email_config)],
        )

    def _email_config(self, flow: HogFlow) -> dict[str, Any]:
        flow.refresh_from_db()
        return next(a for a in flow.actions if a["type"] == "function_email")["config"]

    @parameterized.expand(
        [
            ("no choice made copies the team defaults", {}, True, {"utm_source": "newsletter"}),
            ("an explicit choice is kept", {"utm_tags_enabled": False}, False, None),
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

    def test_apply_utm_defaults_previews_then_updates_only_emails_that_follow_the_defaults(self) -> None:
        legacy_draft = self._flow("Legacy draft", HogFlow.State.DRAFT)
        custom_live = self._flow(
            "Custom live",
            HogFlow.State.ACTIVE,
            utm_tags_enabled=True,
            utm_params={"utm_source": "partner"},
            utm_params_from_default=["utm_medium", "utm_campaign", "utm_content"],
        )
        sent_broadcast = self._flow("Sent broadcast", HogFlow.State.ACTIVE, origin_product="broadcasts")
        archived = self._flow("Archived", HogFlow.State.ARCHIVED)
        legacy_version = legacy_draft.version

        preview = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/apply_utm_defaults", {"dry_run": True}, format="json"
        )

        assert preview.status_code == 200, preview.json()
        assert preview.json() == {
            "emails_updated": 1,
            "workflows_updated": 1,
            "active_workflows_updated": 0,
            "emails_turned_on": 0,
            "emails_off": 1,
            "workflows_failed": 0,
        }
        assert "utm_params" not in self._email_config(legacy_draft)

        applied = self.client.post(
            f"/api/projects/{self.team.id}/hog_flows/apply_utm_defaults",
            {"dry_run": False, "enable_where_off": True},
            format="json",
        )

        assert applied.status_code == 200, applied.json()
        assert applied.json()["emails_turned_on"] == 1
        legacy_config = self._email_config(legacy_draft)
        assert legacy_config["utm_tags_enabled"] is True
        assert legacy_config["utm_params"] == {"utm_source": "newsletter"}
        assert HogFlow.objects.get(pk=legacy_draft.pk).version == legacy_version + 1
        assert self._email_config(custom_live)["utm_params"] == {"utm_source": "partner"}
        assert "utm_params" not in self._email_config(sent_broadcast)
        assert "utm_params" not in self._email_config(archived)
