import json
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.signals.backend.models import (
    SignalActorKind,
    SignalReport,
    SignalReportAction,
    SignalReportArtefact,
    SignalReportAssignment,
)


class TestRecommendations(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.flag = patch("products.signals.backend.views.posthoganalytics.feature_enabled", return_value=True)
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.url = f"/api/projects/{self.team.id}/signals/reports/"

    def report(
        self, *, priority="P1", status="ready", actionability="immediately_actionable", mine=True, addressed=False
    ):
        report = SignalReport.objects.create(
            team=self.team, title="Example finding", summary="Example evidence", status=status
        )
        for kind, payload in [
            ("priority_judgment", {"priority": priority, "explanation": "Example priority"}),
            (
                "actionability_judgment",
                {"actionability": actionability, "already_addressed": addressed, "explanation": "Example action"},
            ),
            ("suggested_reviewers", [{"user_uuid": str(self.user.uuid)}] if mine else []),
        ]:
            SignalReportArtefact.objects.create(team=self.team, report=report, type=kind, content=json.dumps(payload))
        return report

    def shortlist(self, **params):
        response = self.client.get(self.url, {"view": "for_you", **params})
        assert response.status_code == 200, response.json()
        return response.json()["results"]

    def test_priority_order_cap_and_latest_reviewer_correction(self):
        self.report(priority="P2")
        important = self.report(priority="P0")
        for _ in range(6):
            self.report()
        removed = self.report(priority="P0")
        SignalReportArtefact.objects.create(team=self.team, report=removed, type="suggested_reviewers", content="[]")
        rows = self.shortlist(limit=100, ordering="-priority")
        assert len(rows) == 5
        assert rows[0]["id"] == str(important.id)
        assert str(removed.id) not in {r["id"] for r in rows}

    @parameterized.expand(
        [
            ("other_reviewer", {"mine": False}),
            ("low_priority", {"priority": "P3"}),
            ("untriaged", {"priority": None}),
            ("already_handled", {"addressed": True}),
            ("running", {"status": "in_progress"}),
            ("resolved", {"status": "resolved"}),
            ("dismissed", {"status": "suppressed"}),
            ("not_actionable", {"actionability": "not_actionable"}),
        ]
    )
    def test_ineligible_report_stays_out(self, _name, kwargs):
        self.report(**kwargs)
        assert self.shortlist() == []

    def test_claimed_work_stays_out(self):
        report = self.report()
        SignalReportAssignment.all_teams.create(
            team=self.team, report=report, actor_kind=SignalActorKind.USER, actor_user=self.user
        )
        assert self.shortlist() == []

    def test_pending_human_input_is_included(self):
        report = self.report(status="pending_input", actionability="requires_human_input")
        assert self.shortlist()[0]["id"] == str(report.id)

    def test_only_open_pr_is_ready_for_review(self):
        for state in ["open", "draft", "closed", "merged", "unknown"]:
            report = self.report()
            SignalReportAssignment.all_teams.create(
                team=self.team,
                report=report,
                pr_url=f"https://github.com/example/repo/pull/{report.id.int % 10000}",
                pr_state=state,
            )
            if state == "open":
                expected = str(report.id)
        assert [r["id"] for r in self.shortlist()] == [expected]

    def test_snooze_is_personal_reversible_and_expires_without_changing_report(self):
        report = self.report()
        url = f"{self.url}{report.id}/snooze/"
        response = self.client.post(url, {"snoozed": True})
        assert response.status_code == 200, response.json()
        assert response.json()["snoozed_until"]
        assert self.shortlist() == []
        assert self.client.get(self.url).json()["count"] == 1
        report.refresh_from_db()
        assert report.status == "ready"
        SignalReportAction.objects.for_team(self.team.id).filter(type="snooze").update(
            last_at=timezone.now() - timedelta(days=8)
        )
        assert len(self.shortlist()) == 1
        self.client.post(url, {"snoozed": True})
        self.client.post(url, {"snoozed": False})
        assert len(self.shortlist()) == 1
        # Someone else's snooze must not affect the caller.
        other = self._create_user("reader@example.com")
        SignalReportAction.record(
            team_id=self.team.id,
            report_id=str(report.id),
            user_id=other.id,
            action_type=SignalReportAction.ActionType.SNOOZE,
        )
        assert len(self.shortlist()) == 1

    def test_rollout_gate_and_project_isolation(self):
        report = self.report()
        with patch("products.signals.backend.views.posthoganalytics.feature_enabled", return_value=False):
            assert self.client.get(self.url, {"view": "for_you"}).status_code == 403
            assert self.client.post(f"{self.url}{report.id}/snooze/", {"snoozed": True}).status_code == 403
            assert self.client.get(self.url).status_code == 200
        other_team = self.organization.teams.create(name="Other project")
        other = SignalReport.objects.create(team=other_team, status="ready")
        assert self.client.post(f"{self.url}{other.id}/snooze/", {"snoozed": True}).status_code == 404
        assert not SignalReportAction.objects.for_team(other_team.id).exists()
