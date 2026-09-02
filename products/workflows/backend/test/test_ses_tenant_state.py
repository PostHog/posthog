from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.services.ses_tenant_state import (
    PROVIDER_PAUSE_REASON,
    PROVIDER_PAUSE_REASON_UNSPECIFIED,
    apply_ses_tenant_state,
    sync_ses_tenant_state,
)


class TestApplySesTenantState(BaseTest):
    def _apply(self, sending_status: str, reputation_impact: str | None) -> dict:
        with (
            patch("products.workflows.backend.services.ses_tenant_state.send_email_sending_suspended") as suspended,
            patch("products.workflows.backend.services.ses_tenant_state.send_email_sending_unsuspended") as unsuspended,
            patch(
                "products.workflows.backend.services.ses_tenant_state.send_email_sending_reputation_finding"
            ) as finding,
            self.captureOnCommitCallbacks(execute=True),
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

    @parameterized.expand(
        [
            # A healthy or low-impact baseline is silent (rollout must not mass-email)...
            ("healthy", "ENABLED", None, None),
            ("low_findings", "ENABLED", "LOW", None),
            # ...but a tenant that is already paused or already critical is exactly who this
            # feature exists to tell — the first sync must not swallow that.
            ("already_paused", "DISABLED", "HIGH", "suspended"),
            ("already_critical", "ENABLED", "HIGH", "finding"),
        ]
    )
    def test_first_sync_baseline_notifies_only_already_bad_tenants(
        self, _name: str, sending_status: str, impact: str | None, expected_email: str | None
    ) -> None:
        emails = self._apply(sending_status, impact)

        config = TeamWorkflowsConfig.objects.get(team=self.team)
        assert config.ses_tenant_sending_status == sending_status
        assert config.ses_tenant_state_synced_at is not None
        for kind, mock in emails.items():
            assert mock.called == (kind == expected_email), f"{kind} called={mock.called}"

    def test_unchanged_state_only_refreshes_synced_at(self) -> None:
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
            # AWS reports "NONE" rather than an empty impact, so the healthy-to-finding and
            # finding-to-resolved transitions really look like these two rows in production.
            ("first_finding_from_none", "ENABLED", "NONE", "ENABLED", "LOW", "finding"),
            ("finding_resolved_to_none", "ENABLED", "HIGH", "ENABLED", "NONE", None),
            ("escalation", "ENABLED", "LOW", "ENABLED", "HIGH", "finding"),
            ("deescalation", "ENABLED", "HIGH", "ENABLED", "LOW", None),
            # Impact escalating while already paused: the suspension email already covers it
            ("escalation_while_paused", "DISABLED", "LOW", "DISABLED", "HIGH", None),
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
    ) -> None:
        self._seed(previous_status, previous_impact)

        emails = self._apply(new_status, new_impact or None)

        for kind, mock in emails.items():
            assert mock.called == (kind == expected_email), f"{kind} called={mock.called}"

    def test_restore_is_silent_while_staff_kill_switch_still_blocks_sending(self) -> None:
        # AWS reinstating the tenant does not restore delivery while the staff kill switch is set,
        # so a "re-enabled" email would tell admins something false. The admin unsuspend action
        # sends that email when the switch clears.
        TeamWorkflowsConfig.objects.update_or_create(
            team=self.team,
            defaults={"ses_tenant_sending_status": "DISABLED", "email_sending_suspended_at": timezone.now()},
        )

        emails = self._apply("ENABLED", None)

        assert not emails["unsuspended"].called

    def test_provider_pause_email_carries_the_provider_reason(self) -> None:
        self._seed("ENABLED")

        emails = self._apply("DISABLED", "HIGH")

        args = emails["suspended"].call_args.args
        assert args[0] == self.team.id
        assert args[1] == PROVIDER_PAUSE_REASON

    def test_finding_email_carries_the_new_impact(self) -> None:
        self._seed("ENABLED", "LOW")

        emails = self._apply("ENABLED", "HIGH")

        assert emails["finding"].call_args.args[:2] == (self.team.id, "HIGH")

    def test_pause_without_high_impact_does_not_blame_reputation_findings(self) -> None:
        self._seed("ENABLED", "NONE")

        emails = self._apply("DISABLED", "NONE")

        assert emails["suspended"].call_args.args[1] == PROVIDER_PAUSE_REASON_UNSPECIFIED

    def _findings_sent_for(self, findings: list[dict[str, str]]) -> list[dict[str, str]]:
        self._seed("ENABLED", "NONE")
        with (
            patch(
                "products.workflows.backend.services.ses_tenant_state.send_email_sending_reputation_finding"
            ) as finding,
            self.captureOnCommitCallbacks(execute=True),
        ):
            apply_ses_tenant_state(self.team.id, sending_status="ENABLED", reputation_impact="HIGH", findings=findings)
        return finding.delay.call_args.args[3]

    def test_finding_email_uses_our_wording_worst_first_and_drops_unknown_types(self) -> None:
        sent = self._findings_sent_for(
            [
                {"finding_type": "DKIM", "impact": "LOW", "description": "Provider prose we do not show"},
                {"finding_type": "BOUNCE", "impact": "HIGH", "description": ""},
                {"finding_type": "A_TYPE_AWS_ADDED_LATER", "impact": "HIGH", "description": "Unmapped"},
            ]
        )

        assert sent == [
            {"impact": "HIGH", "description": "Stop sending to addresses that have bounced"},
            {"impact": "LOW", "description": "Set up DKIM for your sending domain"},
        ]

    def test_repeated_finding_type_is_collapsed_to_its_worst_impact(self) -> None:
        sent = self._findings_sent_for(
            [
                {"finding_type": "DKIM", "impact": "LOW", "description": ""},
                {"finding_type": "DKIM", "impact": "HIGH", "description": ""},
            ]
        )

        assert sent == [{"impact": "HIGH", "description": "Set up DKIM for your sending domain"}]


class TestSyncSesTenantState(BaseTest):
    def test_unknown_team_is_skipped_without_calling_ses(self) -> None:
        # SES keeps tenants for deleted projects, and the webhook trusts AWS for the team id. A
        # write here would fail the config row's FK and retry forever.
        provider = MagicMock()

        sync_ses_tenant_state(self.team.id + 99_999, provider=provider)

        provider.get_tenant_reputation.assert_not_called()
        assert not TeamWorkflowsConfig.objects.filter(team_id=self.team.id + 99_999).exists()
