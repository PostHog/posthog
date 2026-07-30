from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.ses_tenant_state import PROVIDER_PAUSE_REASON, apply_ses_tenant_state


class TestApplySesTenantState(BaseTest):
    def _apply(self, sending_status: str, reputation_impact: str | None) -> dict:
        with (
            patch("products.workflows.backend.services.ses_tenant_state.send_email_sending_suspended") as suspended,
            patch("products.workflows.backend.services.ses_tenant_state.send_email_sending_unsuspended") as unsuspended,
            patch(
                "products.workflows.backend.services.ses_tenant_state.send_email_sending_reputation_finding"
            ) as finding,
        ):
            apply_ses_tenant_state(self.team.id, sending_status=sending_status, reputation_impact=reputation_impact)
        return {"suspended": suspended.delay, "unsuspended": unsuspended.delay, "finding": finding.delay}

    def _seed(self, sending_status: str, reputation_impact: str = "") -> None:
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "ses_tenant_sending_status": sending_status,
                "ses_tenant_reputation_impact": reputation_impact,
            },
        )

    def test_first_sync_sets_a_baseline_without_notifying(self):
        emails = self._apply("DISABLED", "HIGH")

        config = TeamWorkflowsConfig.objects.get(team=self.team)
        assert config.ses_tenant_sending_status == "DISABLED"
        assert config.ses_tenant_reputation_impact == "HIGH"
        assert config.ses_tenant_state_synced_at is not None
        assert all(not mock.called for mock in emails.values())

    def test_unchanged_state_only_refreshes_synced_at(self):
        self._seed("ENABLED", "LOW")

        emails = self._apply("ENABLED", "LOW")

        assert all(not mock.called for mock in emails.values())
        assert TeamWorkflowsConfig.objects.get(team=self.team).ses_tenant_state_synced_at is not None

    @parameterized.expand(
        [
            # (previous_status, previous_impact, new_status, new_impact, expected_email)
            ("pause", "ENABLED", "", "DISABLED", "HIGH", "suspended"),
            ("pause_from_reinstated", "REINSTATED", "LOW", "DISABLED", "HIGH", "suspended"),
            ("unpause", "DISABLED", "HIGH", "ENABLED", "", "unsuspended"),
            ("reinstate", "DISABLED", "HIGH", "REINSTATED", "HIGH", "unsuspended"),
            ("first_finding", "ENABLED", "", "ENABLED", "LOW", "finding"),
            ("escalation", "ENABLED", "LOW", "ENABLED", "HIGH", "finding"),
            ("deescalation", "ENABLED", "HIGH", "ENABLED", "LOW", None),
            ("finding_resolved", "ENABLED", "LOW", "ENABLED", "", None),
        ]
    )
    def test_transitions_send_the_right_email(
        self,
        _name: str,
        previous_status: str,
        previous_impact: str,
        new_status: str,
        new_impact: str,
        expected_email: str | None,
    ):
        self._seed(previous_status, previous_impact)

        emails = self._apply(new_status, new_impact or None)

        for kind, mock in emails.items():
            assert mock.called == (kind == expected_email), f"{kind} called={mock.called}"

    def test_provider_pause_email_carries_the_provider_reason(self):
        self._seed("ENABLED")

        emails = self._apply("DISABLED", "HIGH")

        args = emails["suspended"].call_args.args
        assert args[0] == self.team.id
        assert args[1] == PROVIDER_PAUSE_REASON

    def test_finding_email_carries_the_new_impact(self):
        self._seed("ENABLED", "LOW")

        emails = self._apply("ENABLED", "HIGH")

        assert emails["finding"].call_args.args[:2] == (self.team.id, "HIGH")
