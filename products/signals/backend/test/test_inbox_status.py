from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.replay_vision.backend.models import ReplayScanner
from products.signals.backend.inbox_status import resolve_setup_state
from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalSourceConfig, SignalTeamConfig


class TestInboxSetupDecision(SimpleTestCase):
    @parameterized.expand(
        [
            (True, False, False, False, False, "not_started"),
            (True, True, False, False, False, "in_progress"),
            (True, True, False, True, False, "in_progress"),
            (True, False, False, True, False, "active"),
            (True, True, True, True, True, "active"),
            (True, True, True, False, False, "paused"),
            (True, False, False, False, True, "paused"),
            (False, False, True, True, True, "ai_disabled"),
        ]
    )
    def test_current_configuration_wins_over_history(
        self, ai: bool, draft: bool, completed: bool, watching: bool, reports: bool, expected: str
    ) -> None:
        assert (
            resolve_setup_state(
                ai_approved=ai, has_draft=draft, completed=completed, watching=watching, has_reports=reports
            )
            == expected
        )


class TestInboxStatus(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/signals/inbox_status/"

    @parameterized.expand(
        [
            ("error_tracking", "issue_created", "active"),
            ("signals_scout", "cross_source_issue", "not_started"),
            ("llm_analytics", "evaluation", "not_started"),
            ("session_replay", "session_analysis_cluster", "not_started"),
        ]
    )
    def test_only_report_producing_sources_count(self, product: str, source: str, expected: str) -> None:
        SignalSourceConfig.objects.create(team=self.team, source_product=product, source_type=source, enabled=True)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json()["setup_state"] == expected

    @parameterized.expand(
        [("team", True, "active"), ("background", True, "not_started"), ("team", False, "not_started")]
    )
    def test_scout_must_be_chosen_and_emit_reports(self, managed_by: str, emit: bool, expected: str) -> None:
        SignalScoutConfig.objects.create(
            team=self.team, skill_name="example-scout", enabled=True, emit=emit, managed_by=managed_by
        )
        assert self.client.get(self.url).json()["setup_state"] == expected

    def test_inbox_read_credential_gets_summary_without_scout_details(self) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", enabled=True
        )
        SignalTeamConfig.objects.create(
            team=self.team,
            onboarding={"completed_at": timezone.now().isoformat(), "first_report": {"status": "no_data"}},
        )
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="inbox",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["inbox:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        response = self.client.get(self.url, HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == 200
        assert response.json() == {
            "setup_state": "active",
            "has_report_history": False,
            "first_report_status": "no_data",
            "can_configure": True,
        }

    def test_handled_reports_are_still_project_history(self) -> None:
        SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.RESOLVED, first_visible_at=timezone.now()
        )
        response = self.client.get(self.url)
        assert response.json()["has_report_history"] is True
        assert response.json()["setup_state"] == "paused"

    def test_legacy_visible_reports_are_still_history(self) -> None:
        SignalReport.objects.create(team=self.team, status=SignalReport.Status.READY)
        assert self.client.get(self.url).json()["has_report_history"] is True

    def test_replay_scanner_can_enable_self_driving_without_a_source_config(self) -> None:
        ReplayScanner.objects.create(team=self.team, name="Example scanner", enabled=True, emits_signals=True)
        assert self.client.get(self.url).json()["setup_state"] == "active"

    def test_paused_scout_does_not_keep_self_driving_active(self) -> None:
        SignalTeamConfig.objects.create(team=self.team, onboarding={"completed_at": timezone.now().isoformat()})
        SignalScoutConfig.objects.create(team=self.team, skill_name="example-scout", enabled=False, emit=True)
        assert self.client.get(self.url).json()["setup_state"] == "paused"

    def test_another_projects_reports_do_not_hide_setup(self) -> None:
        other = Team.objects.create(organization=self.organization)
        SignalReport.objects.create(team=other, status=SignalReport.Status.READY, first_visible_at=timezone.now())
        assert self.client.get(self.url).json()["setup_state"] == "not_started"

    def test_child_only_credential_cannot_read_parent_status(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["inbox:read"],
            scoped_teams=[child.id],
        )
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{child.id}/signals/inbox_status/", HTTP_AUTHORIZATION=f"Bearer {raw}"
        )
        assert response.status_code == 403
