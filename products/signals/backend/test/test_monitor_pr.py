from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Integration, OrganizationMembership, Team, User
from posthog.models.integration import GitHubIntegration
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportSuggestedReviewer
from products.signals.backend.monitor_pr import (
    MonitorPRInput,
    PRMonitoringOutput,
    finish_monitoring_research,
    load_pull_request,
    refresh_monitored_pr,
)
from products.signals.backend.monitor_pr_research import _context
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.test.report_metric_test_fixtures import trends_metric_query

PR_URL = "https://github.com/example/widget/pull/42"


class TestMonitorPR(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        Integration.objects.create(
            team=self.team, kind="github", integration_id="123", config={"organization": "example"}
        )
        self.url = f"/api/projects/{self.team.id}/signals/monitor_pr/"
        self.pr = {
            "success": True,
            "title": "Improve checkout",
            "head_sha": "a" * 40,
            "base_branch": "main",
            "state": "open",
            "merged": False,
            "author": "another-author",
        }
        self.dispatched: dict[str, MonitorPRInput] = {}

        async def start(_run, inputs, **kwargs):
            self.dispatched.setdefault(kwargs["id"], inputs)

        client = AsyncMock()
        client.start_workflow.side_effect = start
        for mock in (
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=True),
            patch.object(
                GitHubIntegration,
                "installation_can_access_repository",
                autospec=True,
                side_effect=lambda integration, repository, **kwargs: repository == "example/widget",
            ),
            patch.object(GitHubIntegration, "get_pull_request", side_effect=lambda *args: self.pr),
            patch("products.signals.backend.temporal.monitor_pr.async_connect", return_value=client),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def request_report(self, note="", expected_status=202):
        response = self.client.post(self.url, {"pr_url": PR_URL, "note": note})
        assert response.status_code == expected_status, response.json()
        report = SignalReport.objects.get(id=response.json()["report_id"])
        return report, next(iter(self.dispatched.values()))

    def output(self):
        return PRMonitoringOutput.model_validate(
            {
                "title": "Checkout completion after the PR",
                "summary": "Measure checkout completions after merge against the observed baseline.",
                "inspected_commit": "a" * 40,
                "metric": {
                    "metric_id": "checkout",
                    "title": "Completed checkouts",
                    "kind": "occurrences",
                    "role": "primary",
                    "value_format": "count",
                    "query": trends_metric_query(series=[{"kind": "EventsNode", "event": "checkout_completed"}]),
                },
                "check": {
                    "title": "Checkout completions",
                    "kind": "metric_threshold",
                    "soak_hours": 24,
                    "config": {
                        "metric_id": "checkout",
                        "comparison": {"operator": "gte", "value": 100},
                        "monitoring": {"reference_period_minutes": 1440, "threshold_scaling": "linear"},
                    },
                },
            }
        )

    @parameterized.expand(
        [("", False), ("Focus on checkout completion for new users.", False), ("Focus on checkout completion.", True)]
    )
    def test_request_assigns_initiator_and_retries_preserve_original_note(self, note, dispatch_fails):
        if dispatch_fails:
            with patch("products.signals.backend.temporal.monitor_pr.async_connect", side_effect=ConnectionError):
                assert self.client.post(self.url, {"pr_url": PR_URL, "note": note}).status_code == 503
        report, inputs = self.request_report(note, expected_status=200 if dispatch_fails else 202)
        assert report.created_by_id == self.user.id
        claim = get_active_claim(team_id=self.team.id, report_id=str(report.id))
        assert claim is not None
        assert claim.actor_user_id == self.user.id
        assert (
            SignalReportSuggestedReviewer.objects.for_team(self.team.id)
            .filter(report_id=report.id, user_uuid=self.user.uuid)
            .exists()
        )
        assert inputs.note == note
        assert (
            self.client.get(f"/api/projects/{self.team.id}/signals/reports/{report.id}/").json()["repo_slug"]
            == "example/widget"
        )
        response = self.client.post(self.url, {"pr_url": PR_URL, "note": "A different focus"})
        assert response.status_code == 200
        assert response.json()["idempotent_replay"] is True
        assert response.json()["report_id"] == str(report.id)
        assert len(self.dispatched) == 1
        assert SignalReport.objects.filter(team=self.team).count() == 1
        assert next(iter(self.dispatched.values())).note == note

    @parameterized.expand([("merged",), ("open",), ("closed",), ("unmeasurable",)])
    def test_research_and_merge_follow_monitoring_lifecycle(self, scenario):
        merged_at = timezone.now() - timedelta(hours=2)
        if scenario == "merged":
            self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
        report, inputs = self.request_report()
        pr = load_pull_request(self.team.id, PR_URL)
        output = self.output()
        if scenario == "unmeasurable":
            output = PRMonitoringOutput(
                title="Missing instrumentation",
                summary="Checkout events are not available.",
                inspected_commit="a" * 40,
                unavailable_reason="Instrument checkout completion first.",
            )
        finish_monitoring_research(inputs, output, pr)
        report.refresh_from_db()
        if scenario == "unmeasurable":
            assert report.status == SignalReport.Status.PENDING_INPUT
            assert not SignalReportCheck.objects.for_team(self.team.id).filter(report=report).exists()
            self.pr.update(state="closed", merged=True, merged_at=merged_at.isoformat())
            from products.signals.backend.pull_requests import update_pull_request_state

            update_pull_request_state(
                team_id=self.team.id, repository="example/widget", number=42, state="merged", merged_at=merged_at
            )
            report.refresh_from_db()
            assert report.status == SignalReport.Status.PENDING_INPUT
            return
        if scenario != "merged":
            assert report.status == SignalReport.Status.READY
            check = SignalReportCheck.objects.for_team(self.team.id).get(report=report)
            assert check.status == SignalReportCheck.Status.PENDING
            self.pr.update(
                state="closed",
                merged=scenario == "open",
                merged_at=merged_at.isoformat() if scenario == "open" else None,
            )
            assert refresh_monitored_pr(inputs) is False
            report.refresh_from_db()
        if scenario == "closed":
            assert report.status == SignalReport.Status.SUPPRESSED
        else:
            assert report.status == SignalReport.Status.MONITORING
            assert report.monitoring_started_at == merged_at
            assert report.metrics[0]["metric_id"] == "checkout"
            assert report.metrics[0]["role"] == "primary"
        claim = get_active_claim(team_id=self.team.id, report_id=str(report.id))
        if scenario == "closed":
            assert claim is None
        else:
            assert claim is not None and claim.actor_user_id == self.user.id
        assert (
            SignalReportSuggestedReviewer.objects.for_team(self.team.id)
            .filter(report_id=report.id, user_uuid=self.user.uuid)
            .exists()
        )

    @parameterized.expand(
        [
            ("https://github.com/unregistered/widget/pull/42",),
            ("https://github.com/example/widget/issues/42",),
            ("https://github.com/example/widget/pull/42/files",),
            (PR_URL, True),
        ]
    )
    def test_only_registered_pull_requests_are_accepted(self, url, other_project=False):
        if other_project:
            other = Team.objects.create(organization=self.organization)
            Integration.objects.filter(team=self.team, kind="github").update(team=other)
        response = self.client.post(self.url, {"pr_url": url})
        assert response.status_code == 400
        assert not SignalReport.objects.filter(team=self.team).exists()

    @parameterized.expand([("scopes",), ("ai_consent",), ("sandbox",)])
    def test_unauthorized_request_cannot_start_research(self, denied):
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="monitor",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["inbox:write"]
            if denied == "scopes"
            else ["inbox:write", "task:write", "query:read", "event_definition:read"],
            scoped_teams=[self.team.id],
        )
        self.client.logout()
        if denied == "ai_consent":
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            self.url,
            {"pr_url": PR_URL},
            HTTP_AUTHORIZATION=f"Bearer {raw}",
            HTTP_X_POSTHOG_SANDBOX_ORIGIN="1" if denied == "sandbox" else "",
        )
        assert response.status_code == 403, response.json()
        assert not self.dispatched
        assert not SignalReport.objects.filter(team=self.team).exists()

    def test_removed_member_cannot_start_queued_research(self):
        _, inputs = self.request_report()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        with self.assertRaises(User.DoesNotExist):
            _context(inputs)
