from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIClient

from posthog.dataclasses import frozen
from posthog.models import OAuthAccessToken, OAuthApplication, Team, User
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV, POSTHOG_AI_APP_CLIENT_ID_DEV, PULSE_ANALYSIS_SCOPES

from products.actions.backend.models.action import Action
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.experiments.backend.facade.contracts import (
    PulseExperimentDraftInput,
    PulseExperimentMetricRef,
    PulseExperimentVariant,
)
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.api import create_flag as create_feature_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.subscriptions.backend.models import ActionProposal, Artifact, Opportunity, PulseRun, RunAction
from products.subscriptions.backend.pulse.contracts import PulseExperimentDraftResultDTO
from products.subscriptions.backend.pulse.experiment_drafts import (
    PulseExperimentDraftNotFound,
    create_pulse_experiment_draft,
    issue_pulse_experiment_draft_token,
)
from products.tasks.backend.facade.testing import (
    create_oauth_access_token_for_run_for_test,
    create_staged_run_transition_for_test,
)
from products.tasks.backend.models import Task, TaskRun


@frozen
class _PulseExperimentDraftFixture:
    run: PulseRun
    task: Task
    analysis_run: TaskRun
    execution_run: TaskRun
    opportunity: Opportunity
    proposal: ActionProposal
    action: RunAction
    artifact: Artifact
    oauth_application: OAuthApplication


def _pulse_experiment_input() -> PulseExperimentDraftInput:
    return PulseExperimentDraftInput(
        name="Improve checkout completion",
        hypothesis="A shorter checkout will increase completed purchases.",
        description="Test a reduced checkout form.",
        target_description="Customers who start checkout.",
        variants=(
            PulseExperimentVariant(key="control", name="Current checkout"),
            PulseExperimentVariant(key="short-form", name="Short checkout"),
        ),
        primary_metric=PulseExperimentMetricRef(kind="event", event_name="purchase_completed"),
        secondary_metrics=(PulseExperimentMetricRef(kind="event", event_name="checkout_started"),),
    )


def _create_pulse_experiment_draft_fixture(*, team: Team, user: User) -> _PulseExperimentDraftFixture:
    run = PulseRun.objects.for_team(team.id).create(
        team=team,
        subscription_id=1,
        delivery_id=uuid4(),
        status=PulseRun.Status.EXECUTING,
        config_snapshot={"actor_id": user.id, "flags": {"allow_experiment_draft": True}},
        report_snapshot_ref="reports/pulse-experiment",
    )
    task = Task.objects.create(
        team=team,
        created_by=user,
        title="Pulse experiment execution",
        description="Create one inert experiment draft.",
        origin_product=Task.OriginProduct.PULSE_SUBSCRIPTION,
        origin_key="pulse-experiment-execution",
        internal=True,
        state={
            "staged_caller_id": str(run.id),
            "staged_idempotency_key": "pulse-experiment-execution",
        },
    )
    analysis_run = TaskRun.objects.create(
        task=task,
        team=team,
        status=TaskRun.Status.COMPLETED,
        state={"snapshot_external_id": "pulse-analysis-snapshot"},
    )
    execution_run = TaskRun.objects.create(
        task=task,
        team=team,
        status=TaskRun.Status.IN_PROGRESS,
        state={},
    )
    manifest = {
        "version": 1,
        "phase": "execution",
        "capabilities": ["read", "experiment_draft"],
        "bindings": {
            "caller_id": str(run.id),
            "task_id": str(task.id),
            "run_id": str(execution_run.id),
            "publication_allowed": False,
        },
    }
    transition_id = create_staged_run_transition_for_test(
        team_id=team.id,
        caller_id=run.id,
        task=task,
        source_task_run=analysis_run,
        successor_task_run=execution_run,
        source_workspace_snapshot_ref="pulse-analysis-snapshot",
        requested_capability_manifest=manifest,
        idempotency_key="pulse-experiment-transition",
    )
    execution_run.state = {
        "staged_phase": "execution",
        "staged_transition_id": str(transition_id),
        "staged_manifest": manifest,
    }
    execution_run.save(update_fields=["state"])
    run.task_id = task.id
    run.analysis_task_run_id = analysis_run.id
    run.execution_task_run_id = execution_run.id
    run.save(update_fields=["task_id", "analysis_task_run_id", "execution_task_run_id"])

    opportunity = Opportunity.objects.for_team(team.id).create(
        team=team,
        stable_key="pulse-experiment-opportunity",
        title="Improve checkout",
        summary="Checkout completion is below its target.",
    )
    proposal = ActionProposal.objects.for_team(team.id).create(
        team=team,
        opportunity=opportunity,
        stable_action_key="pulse-experiment-proposal",
        kind=ActionProposal.Kind.EXPERIMENT_DRAFT,
        normalized_target={"category": "checkout"},
    )
    action = RunAction.objects.for_team(team.id).create(
        team=team,
        run=run,
        opportunity=opportunity,
        proposal=proposal,
        action_key="pulse-experiment-action",
        kind=RunAction.Kind.EXPERIMENT_DRAFT,
        title="Test a shorter checkout",
        rationale="A shorter form may reduce abandonment.",
        expected_impact="More completed purchases.",
        rank=1,
        implementation_selected=True,
        status=RunAction.Status.EXECUTING,
    )
    artifact = Artifact.objects.for_team(team.id).create(
        team=team,
        run=run,
        action=action,
        opportunity=opportunity,
        proposal=proposal,
        kind=Artifact.Kind.EXPERIMENT_DRAFT,
        idempotency_key="pulse-experiment-artifact",
        task_id=task.id,
        execution_task_run_id=execution_run.id,
        status=Artifact.Status.RESERVED,
    )
    EventDefinition.objects.create(team=team, name="purchase_completed")
    EventDefinition.objects.create(team=team, name="checkout_started")
    oauth_application = OAuthApplication.objects.create(
        name="Pulse sandbox test",
        client_id=ARRAY_APP_CLIENT_ID_DEV,
        client_type=OAuthApplication.CLIENT_PUBLIC,
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://example.com/callback",
        algorithm="RS256",
    )
    return _PulseExperimentDraftFixture(
        run=run,
        task=task,
        analysis_run=analysis_run,
        execution_run=execution_run,
        opportunity=opportunity,
        proposal=proposal,
        action=action,
        artifact=artifact,
        oauth_application=oauth_application,
    )


@override_settings(CLOUD_DEPLOYMENT="DEV")
class TestPulseExperimentDrafts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OAuthApplication.objects.create(
            name="PostHog AI Dev App",
            client_id=POSTHOG_AI_APP_CLIENT_ID_DEV,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/posthog-ai/callback",
            algorithm="RS256",
        )
        fixture = _create_pulse_experiment_draft_fixture(team=self.team, user=self.user)
        self.pulse_run = fixture.run
        self.task = fixture.task
        self.analysis_run = fixture.analysis_run
        self.execution_run = fixture.execution_run
        self.opportunity = fixture.opportunity
        self.proposal = fixture.proposal
        self.action = fixture.action
        self.artifact = fixture.artifact
        self.oauth_application = fixture.oauth_application

    def _request_data(self) -> dict[str, object]:
        return {
            "name": "Improve checkout completion",
            "hypothesis": "A shorter checkout will increase completed purchases.",
            "description": "Test a reduced checkout form.",
            "target_description": "Customers who start checkout.",
            "variants": [
                {"key": "control", "name": "Current checkout"},
                {"key": "short-form", "name": "Short checkout"},
            ],
            "primary_metric": {"kind": "event", "event_name": "purchase_completed"},
            "secondary_metrics": [{"kind": "event", "event_name": "checkout_started"}],
        }

    def _sandbox_client(self, token: str) -> APIClient:
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def _raw_oauth_token(
        self,
        *,
        scope: str,
        sandbox_task_id: UUID | None = None,
        scoped_teams: list[int] | None = None,
        user: User | None = None,
        application: OAuthApplication | None = None,
    ) -> OAuthAccessToken:
        return OAuthAccessToken.objects.create(
            user=user or self.user,
            application=application or self.oauth_application,
            token=f"pha_pulse_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
            scoped_teams=scoped_teams if scoped_teams is not None else [self.team.id],
            sandbox_task_id=sandbox_task_id,
        )

    def _input_dto(self) -> PulseExperimentDraftInput:
        return _pulse_experiment_input()

    def test_issuer_mints_only_the_exact_private_execution_posture(self) -> None:
        token = create_oauth_access_token_for_run_for_test(self.task, self.execution_run.state)

        access_token = OAuthAccessToken.objects.get(token=token)
        assert access_token.application is not None
        assert access_token.application.client_id == POSTHOG_AI_APP_CLIENT_ID_DEV
        assert access_token.sandbox_task_id == self.task.id
        assert access_token.user_id == self.user.id
        assert set(access_token.scope.split()) == {*PULSE_ANALYSIS_SCOPES, "pulse_experiment_draft:write"}
        assert "task:write" not in access_token.scope.split()

    def test_api_creates_one_inert_draft_and_exact_retry_returns_it(self) -> None:
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        client = self._sandbox_client(token)
        url = f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/"

        first = client.post(url, self._request_data(), format="json")
        second = client.post(url, self._request_data(), format="json")

        assert first.status_code == status.HTTP_201_CREATED, first.json()
        assert second.status_code == status.HTTP_200_OK, second.json()
        assert first.json() == second.json()
        assert Experiment.objects.filter(team=self.team).count() == 1
        assert FeatureFlag.objects.filter(team=self.team).count() == 1
        experiment = Experiment.objects.get(team=self.team)
        assert experiment.is_draft
        assert experiment.start_date is None
        assert experiment.end_date is None
        assert experiment.feature_flag.active is False
        assert experiment.feature_flag.filters["groups"][0]["rollout_percentage"] == 0
        self.artifact.refresh_from_db()
        self.action.refresh_from_db()
        assert self.artifact.status == Artifact.Status.VERIFIED
        assert self.artifact.experiment_id == experiment.id
        assert self.artifact.metadata["feature_flag_id"] == experiment.feature_flag_id
        assert self.action.status == RunAction.Status.COMPLETED

    def test_api_denies_session_unbound_and_other_task_tokens(self) -> None:
        url = f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/"

        session_response = self.client.post(url, self._request_data(), format="json")
        unbound = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token=f"pha_pulse_unbound_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope="pulse_experiment_draft:write",
            scoped_teams=[self.team.id],
        )
        other_task = OAuthAccessToken.objects.create(
            user=self.user,
            application=self.oauth_application,
            token=f"pha_pulse_other_{uuid4().hex}",
            expires=timezone.now() + timedelta(hours=1),
            scope=" ".join((*PULSE_ANALYSIS_SCOPES, "pulse_experiment_draft:write")),
            scoped_teams=[self.team.id],
            sandbox_task_id=uuid4(),
        )

        assert session_response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}
        assert self._sandbox_client(unbound.token).post(url, self._request_data(), format="json").status_code == 403
        assert self._sandbox_client(other_task.token).post(url, self._request_data(), format="json").status_code == 404
        assert Experiment.objects.filter(team=self.team).count() == 0

    def test_api_denies_every_non_exact_token_posture_without_mutating_the_reservation(self) -> None:
        url = f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/"
        exact_scope = " ".join((*PULSE_ANALYSIS_SCOPES, "pulse_experiment_draft:write"))
        other_user = self._create_user("pulse-other-user@example.com", "testpassword12345")
        other_application = OAuthApplication.objects.create(
            name="Untrusted OAuth client",
            client_id=f"untrusted-{uuid4().hex}",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/untrusted",
            algorithm="RS256",
        )
        tokens = [
            self._raw_oauth_token(
                scope=exact_scope,
                sandbox_task_id=self.task.id,
                user=other_user,
            ),
            self._raw_oauth_token(
                scope=exact_scope,
                sandbox_task_id=self.task.id,
                scoped_teams=[self.team.id + 1],
            ),
            self._raw_oauth_token(
                scope=exact_scope,
                sandbox_task_id=self.task.id,
                application=other_application,
            ),
            self._raw_oauth_token(
                scope=" ".join(PULSE_ANALYSIS_SCOPES),
                sandbox_task_id=self.task.id,
            ),
            self._raw_oauth_token(
                scope=f"{exact_scope} task:write",
                sandbox_task_id=self.task.id,
            ),
        ]

        for token in tokens:
            response = self._sandbox_client(token.token).post(url, self._request_data(), format="json")
            assert response.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}

        self.artifact.refresh_from_db()
        assert self.artifact.status == Artifact.Status.RESERVED
        assert self.artifact.metadata == {}
        assert Experiment.objects.filter(team=self.team).count() == 0
        assert FeatureFlag.objects.filter(team=self.team).count() == 0

    def test_changed_retry_and_widened_fields_are_rejected(self) -> None:
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        client = self._sandbox_client(token)
        url = f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/"
        assert client.post(url, self._request_data(), format="json").status_code == 201

        changed = {**self._request_data(), "name": "A different experiment"}
        widened = {**self._request_data(), "feature_flag_key": "existing-flag"}

        assert client.post(url, changed, format="json").status_code == 409
        response = client.post(url, widened, format="json")
        assert response.status_code == 400
        assert response.json()["attr"] == "feature_flag_key"
        assert Experiment.objects.filter(team=self.team).count() == 1

    def test_nested_widened_metric_is_rejected_before_any_write(self) -> None:
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        client = self._sandbox_client(token)
        url = f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/"
        request_data = self._request_data()
        request_data["primary_metric"] = {
            "kind": "event",
            "event_name": "purchase_completed",
            "query": {"kind": "HogQLQuery", "query": "select 1"},
        }

        response = client.post(url, request_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Experiment.objects.filter(team=self.team).count() == 0
        assert FeatureFlag.objects.filter(team=self.team).count() == 0

    def test_private_draft_token_cannot_mutate_generic_experiment_or_flag_apis(self) -> None:
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        client = self._sandbox_client(token)
        draft_response = client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/",
            self._request_data(),
            format="json",
        )
        assert draft_response.status_code == status.HTTP_201_CREATED
        experiment = Experiment.objects.get(team=self.team)
        flag = experiment.feature_flag

        create_response = client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": "Generic experiment", "feature_flag_key": "generic-flag"},
            format="json",
        )
        experiment_response = client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment.id}/",
            {"name": "Mutated by generic API"},
            format="json",
        )
        flag_response = client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"active": True},
            format="json",
        )

        assert create_response.status_code == status.HTTP_403_FORBIDDEN
        assert experiment_response.status_code == status.HTTP_403_FORBIDDEN
        assert flag_response.status_code == status.HTTP_403_FORBIDDEN
        experiment.refresh_from_db()
        flag.refresh_from_db()
        assert experiment.name == "Improve checkout completion"
        assert flag.active is False

    def test_foreign_team_action_metric_is_rejected_before_flag_creation(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other metric team")
        foreign_action = Action.objects.create(team=other_team, name="Foreign checkout")
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        request_data = self._request_data()
        request_data["primary_metric"] = {"kind": "action", "action_id": foreign_action.id}

        response = self._sandbox_client(token).post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/",
            request_data,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Experiment.objects.filter(team=self.team).count() == 0
        assert FeatureFlag.objects.filter(team=self.team).count() == 0

    def test_phase_two_failure_leaves_only_a_recoverable_inert_flag(self) -> None:
        with patch(
            "products.subscriptions.backend.pulse.experiment_drafts.create_pulse_experiment_draft_experiment",
            side_effect=RuntimeError("late persistence failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "late persistence failure"):
                create_pulse_experiment_draft(
                    team_id=self.team.id,
                    task_id=self.task.id,
                    actor_id=self.user.id,
                    input_dto=self._input_dto(),
                )

        self.artifact.refresh_from_db()
        orphan_flag = FeatureFlag.objects.get(team=self.team)
        assert self.artifact.status == Artifact.Status.CREATING
        assert self.artifact.experiment_id is None
        assert Experiment.objects.filter(team=self.team).count() == 0
        assert orphan_flag.active is False
        assert orphan_flag.filters["groups"][0]["rollout_percentage"] == 0

        result = create_pulse_experiment_draft(
            team_id=self.team.id,
            task_id=self.task.id,
            actor_id=self.user.id,
            input_dto=self._input_dto(),
        )

        self.artifact.refresh_from_db()
        assert result.created is True
        assert Experiment.objects.filter(team=self.team).count() == 1
        assert FeatureFlag.objects.filter(team=self.team).count() == 1
        assert self.artifact.status == Artifact.Status.VERIFIED

    def test_service_denies_cross_graph_and_cancelled_authority(self) -> None:
        self.artifact.task_id = uuid4()
        self.artifact.save(update_fields=["task_id"])

        with self.assertRaises(PulseExperimentDraftNotFound):
            create_pulse_experiment_draft(
                team_id=self.team.id,
                task_id=self.task.id,
                actor_id=self.user.id,
                input_dto=self._input_dto(),
            )

        self.artifact.task_id = self.task.id
        self.artifact.save(update_fields=["task_id"])
        token = issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        self.pulse_run.status = PulseRun.Status.CANCELLED
        self.pulse_run.finished_at = timezone.now()
        self.pulse_run.save(update_fields=["status", "finished_at"])

        response = self._sandbox_client(token).post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/experiment-drafts/",
            self._request_data(),
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        with self.assertRaises(PulseExperimentDraftNotFound):
            issue_pulse_experiment_draft_token(team_id=self.team.id, task_id=self.task.id)
        assert Experiment.objects.filter(team=self.team).count() == 0
        assert FeatureFlag.objects.filter(team=self.team).count() == 0

    def test_service_denies_a_cross_team_pulse_graph(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other Pulse team")
        other_run = PulseRun.objects.for_team(other_team.id).create(
            team=other_team,
            subscription_id=2,
            delivery_id=uuid4(),
            status=PulseRun.Status.EXECUTING,
            config_snapshot={"actor_id": self.user.id, "flags": {"allow_experiment_draft": True}},
            report_snapshot_ref="reports/other-pulse",
        )
        other_opportunity = Opportunity.objects.for_team(other_team.id).create(
            team=other_team,
            stable_key="other-opportunity",
            title="Other opportunity",
            summary="Belongs to another team.",
        )
        other_proposal = ActionProposal.objects.for_team(other_team.id).create(
            team=other_team,
            opportunity=other_opportunity,
            stable_action_key="other-proposal",
            kind=ActionProposal.Kind.EXPERIMENT_DRAFT,
            normalized_target={"category": "other"},
        )
        other_action = RunAction.objects.for_team(other_team.id).create(
            team=other_team,
            run=other_run,
            opportunity=other_opportunity,
            proposal=other_proposal,
            action_key="other-action",
            kind=RunAction.Kind.EXPERIMENT_DRAFT,
            title="Other experiment",
            rationale="Other rationale.",
            expected_impact="Other impact.",
            rank=1,
            implementation_selected=True,
            status=RunAction.Status.EXECUTING,
        )
        self.artifact.action = other_action
        self.artifact.opportunity = other_opportunity
        self.artifact.proposal = other_proposal
        self.artifact.save(update_fields=["action", "opportunity", "proposal"])

        with self.assertRaises(PulseExperimentDraftNotFound):
            create_pulse_experiment_draft(
                team_id=self.team.id,
                task_id=self.task.id,
                actor_id=self.user.id,
                input_dto=self._input_dto(),
            )

        assert Experiment.objects.filter(team=self.team).count() == 0
        assert FeatureFlag.objects.filter(team=self.team).count() == 0


@override_settings(CLOUD_DEPLOYMENT="DEV")
class TestPulseExperimentDraftConcurrency(NonAtomicAPIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.fixture = _create_pulse_experiment_draft_fixture(team=self.team, user=self.user)

    def test_identical_concurrent_calls_create_one_exact_draft(self) -> None:
        create_flag_barrier = Barrier(2)

        def synchronized_create_flag(
            data: dict[str, object], *, team: Team, user: User, request: object | None = None
        ) -> FeatureFlag:
            create_flag_barrier.wait(timeout=10)
            return create_feature_flag(data, team=team, user=user, request=request)

        def create_from_independent_connection() -> PulseExperimentDraftResultDTO:
            close_old_connections()
            try:
                return create_pulse_experiment_draft(
                    team_id=self.team.id,
                    task_id=self.fixture.task.id,
                    actor_id=self.user.id,
                    input_dto=_pulse_experiment_input(),
                )
            finally:
                close_old_connections()

        with patch(
            "products.experiments.backend.pulse_experiment_draft_service.create_flag",
            side_effect=synchronized_create_flag,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(create_from_independent_connection) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]

        self.fixture.artifact.refresh_from_db()
        self.fixture.action.refresh_from_db()
        experiment = Experiment.objects.get(team=self.team)
        feature_flag = FeatureFlag.objects.get(team=self.team)
        assert sorted(result.created for result in results) == [False, True]
        assert {result.experiment_id for result in results} == {experiment.id}
        assert {result.feature_flag_id for result in results} == {feature_flag.id}
        assert self.fixture.artifact.status == Artifact.Status.VERIFIED
        assert self.fixture.artifact.experiment_id == experiment.id
        assert self.fixture.action.status == RunAction.Status.COMPLETED
