from datetime import UTC, datetime
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, PULSE_ANALYSIS_SCOPES

from products.subscriptions.backend.models import ActionProposal, Opportunity, OutcomePlan, PulseRun, RunAction
from products.tasks.backend.models import Task, TaskRun


@override_settings(CLOUD_DEPLOYMENT="DEV")
class TestPulseOutcomeReplays(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.pulse_run = PulseRun.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=1,
            delivery_id=uuid4(),
            status=PulseRun.Status.ANALYZING,
            config_snapshot={"actor_id": self.user.id},
            report_snapshot_ref="reports/pulse-outcome-replay",
        )
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Pulse outcome replay",
            description="Measure a claimed Pulse outcome.",
            origin_product=Task.OriginProduct.PULSE_SUBSCRIPTION,
            origin_key=f"pulse:{self.pulse_run.id}:analysis",
            internal=True,
            state={
                "staged_caller_id": str(self.pulse_run.id),
                "staged_idempotency_key": f"pulse:{self.pulse_run.id}:analysis",
                "staged_mcp_scope_preset": "pulse_analysis",
            },
        )
        self.analysis_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "staged_phase": "analysis",
                "staged_manifest": {
                    "version": 1,
                    "phase": "analysis",
                    "capabilities": ["read", "research"],
                    "bindings": {
                        "caller_id": str(self.pulse_run.id),
                        "task_id": str(self.task.id),
                        "run_id": "pending",
                        "publication_allowed": False,
                    },
                },
            },
        )
        state = dict(self.analysis_run.state)
        manifest = dict(state["staged_manifest"])
        bindings = dict(manifest["bindings"])
        bindings["run_id"] = str(self.analysis_run.id)
        manifest["bindings"] = bindings
        state["staged_manifest"] = manifest
        self.analysis_run.state = state
        self.analysis_run.save(update_fields=["state", "updated_at"])
        self.pulse_run.task_id = self.task.id
        self.pulse_run.analysis_task_run_id = self.analysis_run.id
        self.pulse_run.save(update_fields=["task_id", "analysis_task_run_id", "updated_at"])

        opportunity = Opportunity.objects.for_team(self.team.id).create(
            team=self.team,
            stable_key="outcome-replay-opportunity",
            title="Improve checkout",
            summary="Checkout completion should improve.",
        )
        proposal = ActionProposal.objects.for_team(self.team.id).create(
            team=self.team,
            opportunity=opportunity,
            stable_action_key="outcome-replay-proposal",
            kind=ActionProposal.Kind.RECOMMENDATION,
            normalized_target={"category": "checkout"},
        )
        action = RunAction.objects.for_team(self.team.id).create(
            team=self.team,
            run=self.pulse_run,
            opportunity=opportunity,
            proposal=proposal,
            action_key="outcome-replay-action",
            kind=RunAction.Kind.RECOMMENDATION,
            title="Simplify checkout",
            rationale="A shorter flow can reduce abandonment.",
            expected_impact="More checkout completions.",
            rank=1,
            metric_direction=RunAction.MetricDirection.INCREASE,
        )
        self.plan = OutcomePlan.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=self.pulse_run.subscription_id,
            proposal=proposal,
            source_action=action,
            measurement_spec={
                "version": 1,
                "adapter_version": "v1",
                "tool_name": "data-catalog-metric-run",
                "tool_schema_version": "v1",
                "replay_arguments": {
                    "name": "checkout-completion",
                    "date_from": "2026-01-01T00:00:00+00:00",
                    "date_to": "2026-01-08T00:00:00+00:00",
                    "interval": "day",
                },
                "selector": {},
                "extraction_kind": "metric_count",
            },
            baseline_value=10,
            baseline_from=datetime(2026, 1, 1, tzinfo=UTC),
            baseline_to=datetime(2026, 1, 8, tzinfo=UTC),
            adoption_status=OutcomePlan.AdoptionStatus.ADOPTED,
            readout_status=OutcomePlan.ReadoutStatus.MEASURING,
            next_readout_at=datetime(2026, 1, 15, tzinfo=UTC),
            claimed_by_run=self.pulse_run,
        )
        self.oauth_application = OAuthApplication.objects.create(
            name="Pulse outcome replay sandbox",
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
        )

    def _token(
        self,
        *,
        scope: str | None = None,
        task_id: UUID | None = None,
        user_id: int | None = None,
    ) -> str:
        token = f"pha_pulse_replay_{uuid4().hex}"
        OAuthAccessToken.objects.create(
            user_id=user_id or self.user.id,
            application=self.oauth_application,
            token=token,
            expires=datetime(2026, 12, 1, tzinfo=UTC),
            scope=scope or " ".join(PULSE_ANALYSIS_SCOPES),
            scoped_teams=[self.team.id],
            sandbox_task_id=task_id if task_id is not None else self.task.id,
        )
        return token

    def _client(self, token: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/subscriptions/pulse/outcome-replays/{self.plan.id}/"

    def test_returns_only_the_server_derived_claimed_measurement_instruction(self) -> None:
        response = self._client(self._token()).get(self._url())

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body == {
            "plan_id": str(self.plan.id),
            "tool_name": "data-catalog-metric-run",
            "tool_schema_version": "v1",
            "comparison_arguments": {
                "name": "checkout-completion",
                "date_from": "2026-01-08T00:00:00+00:00",
                "date_to": "2026-01-15T00:00:00+00:00",
                "interval": "day",
            },
            "selector": {},
        }
        assert "baseline_value" not in body
        assert "measurement_spec" not in body

    def test_denies_wrong_task_actor_or_inactive_analysis_binding(self) -> None:
        other_user = self._create_user("other@example.com", "testpassword12345")
        assert self._client(self._token(task_id=uuid4())).get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        assert (
            self._client(self._token(user_id=other_user.id)).get(self._url()).status_code == status.HTTP_404_NOT_FOUND
        )

        self.analysis_run.status = TaskRun.Status.COMPLETED
        self.analysis_run.save(update_fields=["status", "updated_at"])
        assert self._client(self._token()).get(self._url()).status_code == status.HTTP_404_NOT_FOUND

    def test_denies_non_exact_scope_postures(self) -> None:
        assert self._client(self._token(scope=" ".join(PULSE_ANALYSIS_SCOPES[:-1]))).get(self._url()).status_code == 403
        assert (
            self._client(self._token(scope=" ".join((*PULSE_ANALYSIS_SCOPES, "task:write"))))
            .get(self._url())
            .status_code
            == 403
        )

    def test_denies_a_task_without_the_exact_staged_analysis_identity(self) -> None:
        self.task.origin_product = Task.OriginProduct.POSTHOG_AI
        self.task.save(update_fields=["origin_product", "updated_at"])
        assert self._client(self._token()).get(self._url()).status_code == status.HTTP_404_NOT_FOUND

        self.task.origin_product = Task.OriginProduct.TASK_ANALYSIS
        self.task.save(update_fields=["origin_product", "updated_at"])
        assert self._client(self._token()).get(self._url()).status_code == status.HTTP_404_NOT_FOUND

        self.task.origin_product = Task.OriginProduct.PULSE_SUBSCRIPTION
        self.task.save(update_fields=["origin_product", "updated_at"])
        state = dict(self.analysis_run.state)
        manifest = dict(state["staged_manifest"])
        manifest["capabilities"] = ["read", "research", "draft"]
        state["staged_manifest"] = manifest
        self.analysis_run.state = state
        self.analysis_run.save(update_fields=["state", "updated_at"])
        assert self._client(self._token()).get(self._url()).status_code == status.HTTP_404_NOT_FOUND
