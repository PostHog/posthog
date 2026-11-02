from __future__ import annotations

import json
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.scopes import SCOUT_MONITORING_RESULT_SCOPE

from products.signals.backend.models import (
    SignalReport,
    SignalReportCheck,
    SignalReportMonitoringResult,
    SignalScoutRun,
)
from products.signals.backend.test.test_report_check_final_agents import FinalAuthoredAgentChecksSetup
from products.tasks.backend.facade.testing import create_task_run_oauth_access_token


class TestMonitoringScoutSubmission(FinalAuthoredAgentChecksSetup, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.application = OAuthApplication.objects.create(
            name="Synthetic Monitoring scout",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8237/callback",
            algorithm="RS256",
        )

    def _authenticate(self, run: SignalScoutRun, *, scope_override: str | None = None) -> OAuthAccessToken:
        with (
            patch("posthog.temporal.oauth.get_sandbox_oauth_app", return_value=self.application),
            patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=False),
        ):
            raw = create_task_run_oauth_access_token(
                team_id=self.team.id, task_run_id=run.task_run_id, user_id=self.user.id
            )
        token = OAuthAccessToken.objects.get(token=raw)
        if scope_override is not None:
            token.scope = scope_override
            token.save(update_fields=["scope"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
        return token

    def _url(self, run: SignalScoutRun) -> str:
        return f"/api/projects/{self.team.id}/signals/scout/runs/{run.id}/monitoring_result/"

    @parameterized.expand(
        [
            "missing",
            "string_boolean",
            "wrong_list",
            "extra_identity",
            "sufficient_null",
            "unsupported_boolean",
            "empty_ref",
        ]
        + [
            f"{character}_{field}"
            for character in ("null", "surrogate")
            for field in ("evidence_reason", "explanation", "evidence_refs")
        ]
    )
    def test_invalid_submission_can_be_corrected_in_the_same_run(self, shape: str) -> None:
        run = self._run("Investigating the assigned check.", status="in_progress")
        if shape == "missing":
            task = run.task_run.task
            task.state = {"mcp_builtin_agent_key": "scout", "mcp_tool_allowlist": []}
            task.save(update_fields=["state"])
        token = self._authenticate(run)
        assert SCOUT_MONITORING_RESULT_SCOPE in token.scope.split()
        assert token.scoped_teams == [self.team.id]
        payload = json.loads(self._payload("sufficient", True))
        invalid = dict(payload)
        if shape == "missing":
            invalid.pop("explanation")
        elif shape == "string_boolean":
            invalid["expectation_matches"] = "false"
        elif shape == "wrong_list":
            invalid["evidence_refs"] = "not a list"
        elif shape == "extra_identity":
            invalid["check_id"] = str(uuid4())
        elif shape == "sufficient_null":
            invalid["expectation_matches"] = None
        elif shape == "unsupported_boolean":
            invalid["evidence_status"] = "unsupported"
        elif shape == "empty_ref":
            invalid["evidence_refs"] = [" "]
        else:
            character, field = shape.split("_", 1)
            value = chr(0) if character == "null" else chr(0xD800)
            invalid[field] = [value] if field == "evidence_refs" else value
        rejected = self.client.post(self._url(run), json.dumps(invalid), content_type="application/json")
        assert rejected.status_code == 400, rejected.data
        assert rejected.data
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
        accepted = self.client.post(self._url(run), payload, format="json")
        assert accepted.status_code == 200, accepted.data
        assert accepted.data["accepted"] is True
        result = SignalReportMonitoringResult.objects.for_team(self.team.id).get()
        assert result.outcome == "passed" and result.evidence_status == "sufficient"
        assert result.attempt_id == self.attempt.id and result.submission_id == self.binding.submission_id
        assert result.window_start == self.binding.window_start and result.window_end == self.binding.window_end
        self.report.refresh_from_db()
        run.task_run.refresh_from_db()
        assert self.report.status == SignalReport.Status.MONITORING
        assert run.task_run.status == "in_progress"

    def test_accepted_submission_is_immutable_and_retryable_after_task_finalization(self) -> None:
        run = self._run("Submitting the verdict.", status="in_progress")
        self._authenticate(run)
        payload = json.loads(self._payload("sufficient", True))
        first = self.client.post(self._url(run), payload, format="json")
        assert first.status_code == 200, first.data
        refreshed = self._authenticate(run)
        assert SCOUT_MONITORING_RESULT_SCOPE in refreshed.scope.split()
        run.task_run.status = "completed"
        run.task_run.save(update_fields=["status"])
        repeated = self.client.post(self._url(run), payload, format="json")
        assert repeated.status_code == 200 and repeated.data == first.data
        payload["expectation_matches"] = False
        conflict = self.client.post(self._url(run), payload, format="json")
        assert conflict.status_code == 409, conflict.data
        assert SignalReportMonitoringResult.objects.for_team(self.team.id).get().outcome == "passed"

    @parameterized.expand(["schedule", "manual", "check", "workflow", "experiment"])
    def test_other_scout_types_receive_no_submission_capability(self, trigger: str) -> None:
        run = self._run("Ordinary scout run.", status="in_progress")
        run.metadata = {"run_note": self.note, "triggered_by": trigger}
        run.save(update_fields=["metadata"])
        token = self._authenticate(run)
        assert SCOUT_MONITORING_RESULT_SCOPE not in token.scope.split()
        response = self.client.post(self._url(run), json.loads(self._payload()), format="json")
        assert response.status_code == 403, response.data
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()

    @parameterized.expand(
        [
            "wildcard",
            "ordinary_with_forged_scope",
            "wrong_run",
            "changed",
            "cancelled",
            "flag_off",
            "unbound",
            "session",
            "completed",
            "malformed",
        ]
    )
    def test_capability_and_current_ownership_are_both_required(self, case: str) -> None:
        run = self._run("Investigating.", status="in_progress")
        token = self._authenticate(run, scope_override="*" if case == "wildcard" else None)
        expected = 403 if case == "wildcard" else 400
        if case == "ordinary_with_forged_scope":
            run.metadata = {"triggered_by": "schedule"}
            run.save(update_fields=["metadata"])
        elif case == "wrong_run":
            run = self._run("Another task's run.", status="in_progress")
            expected = 404
        elif case == "changed":
            self.check.title = "A changed expectation"
            self.check.save(update_fields=["title"])
        elif case == "cancelled":
            self.check.status = SignalReportCheck.Status.CANCELLED
            self.check.save(update_fields=["status"])
        elif case == "flag_off":
            self.flag.stop()
        elif case == "unbound":
            token.sandbox_task_id = None
            token.save(update_fields=["sandbox_task_id"])
            expected = 404
        elif case == "session":
            self.client.credentials()
            self.client.force_login(self.user)
            expected = 403
        elif case == "completed":
            run.task_run.status = "completed"
            run.task_run.save(update_fields=["status"])
        elif case == "malformed":
            run.metadata = {"triggered_by": "monitoring", "run_note": "not JSON"}
            run.save(update_fields=["metadata"])
        response = self.client.post(self._url(run), json.loads(self._payload()), format="json")
        assert response.status_code == expected, response.data
        assert not SignalReportMonitoringResult.objects.for_team(self.team.id).exists()
