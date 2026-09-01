from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from products.subscriptions.backend.facade.pulse import (
    PulseSubscriptionNotFound,
    PulseValidationError,
    configure_proactive_subscription,
    create_pulse_run_snapshot,
    get_proactive_configuration_options,
    list_pulse_history,
)
from products.subscriptions.backend.presentation.serializers import OutcomeDecisionSerializer
from products.subscriptions.backend.pulse.contracts import ProactiveConfigInput, PulseRunSnapshotInput
from products.subscriptions.backend.pulse.models import (
    ActionProposal,
    Artifact,
    DeliveryLedger,
    EvidenceRawBody,
    EvidenceSet,
    EvidenceToolCall,
    Opportunity,
    OutcomeObservation,
    OutcomePlan,
    ProactiveSubscriptionConfig,
    PublicResearchSubject,
    PulseRun,
    RepositoryGrant,
    RunAction,
)
from products.tasks.backend.facade.contracts import (
    AuthorizableRepositoryDTO,
    PublicationGateDTO,
    StagedDraftPublicationDTO,
)

from ee.api.test import test_subscription as subscription_test


class TestOutcomeDecisionSerializer(SimpleTestCase):
    @parameterized.expand(
        [("missing", {}), ("unknown", {"decision": "ignored"}), ("extra", {"decision": "adopted", "x": 1})]
    )
    def test_rejects_invalid_decisions(self, _name: str, data: dict[str, object]) -> None:
        serializer = OutcomeDecisionSerializer(data=data)

        assert not serializer.is_valid()


class TestPulsePresentationAccess(subscription_test.TestSubscriptionObjectAccessControl):
    """Exercise Pulse routes with the real subscription access-control fixture."""

    def _run_for(self, subscription_id: int, contexts: list[dict[str, int]]) -> PulseRun:
        return PulseRun.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=subscription_id,
            delivery_id=uuid4(),
            config_snapshot={"contexts": contexts},
            report_snapshot_ref="reports/test",
        )

    def _action_for(self, run: PulseRun, *, index: int = 1) -> RunAction:
        opportunity = Opportunity.objects.for_team(self.team.id).create(
            team=self.team, stable_key=f"opportunity:{run.id}:{index}", title="Title", summary="Summary"
        )
        proposal = ActionProposal.objects.for_team(self.team.id).create(
            team=self.team,
            opportunity=opportunity,
            stable_action_key=f"proposal:{run.id}:{index}",
            kind=ActionProposal.Kind.RECOMMENDATION,
            normalized_target={},
        )
        return RunAction.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"action:{run.id}:{index}",
            kind=RunAction.Kind.RECOMMENDATION,
            title="Title",
            rationale="Rationale",
            expected_impact="Impact",
            rank=index,
            readout_after_days=7,
        )

    def _plan_for(self, action: RunAction) -> OutcomePlan:
        now = timezone.now()
        return OutcomePlan.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=action.run.subscription_id,
            proposal=action.proposal,
            source_action=action,
            measurement_spec={"version": 1},
            baseline_value=10,
            baseline_from=now - timedelta(days=7),
            baseline_to=now,
        )

    def _enable_snapshot(self, subscription_id: int) -> None:
        ProactiveSubscriptionConfig.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=subscription_id,
            enabled=True,
            create_draft_pr=False,
        )

    def _snapshot_input(self, contexts: list[dict[str, int]]) -> PulseRunSnapshotInput:
        return PulseRunSnapshotInput(
            delivery_id=uuid4(),
            report_snapshot_ref="reports/test",
            original_prompt="Find the next product improvement.",
            contexts=contexts,
            limits={"max_actions": 1},
            flags={},
            actor_id=self.user.id,
            integration_id=None,
            model_version="model-v1",
            normalizer_model_version="normalizer-v1",
        )

    def test_snapshot_allows_the_owner_with_the_exact_accessible_contexts_without_a_draft_pr(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._enable_snapshot(subscription.id)
        snapshot_input = self._snapshot_input([{"insight_id": self.open_insight.id}])

        run = create_pulse_run_snapshot(
            team_id=self.team.id,
            subscription_id=subscription.id,
            snapshot_input=snapshot_input,
        )

        assert run.delivery_id == snapshot_input.delivery_id
        assert run.config_snapshot["contexts"] == [{"insight_id": self.open_insight.id}]

    def test_snapshot_accepts_only_current_server_emitted_limit_keys_and_bounds(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._enable_snapshot(subscription.id)
        snapshot_input = self._snapshot_input([{"insight_id": self.open_insight.id}])
        snapshot_input = replace(
            snapshot_input,
            limits={
                "max_actions": 1,
                "max_tool_calls": 20,
                "max_runtime_seconds": 3600,
                "max_public_research_calls": 3,
                "max_agent_context_tokens": 200_000,
            },
        )

        run = create_pulse_run_snapshot(
            team_id=self.team.id,
            subscription_id=subscription.id,
            snapshot_input=snapshot_input,
        )

        assert run.config_snapshot["limits"] == snapshot_input.limits

        with self.assertRaisesRegex(ValueError, "limits contain an invalid key or value"):
            create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription.id,
                snapshot_input=replace(
                    snapshot_input,
                    delivery_id=uuid4(),
                    limits={**snapshot_input.limits, "max_agent_context_tokens": 200_001},
                ),
            )

    def test_snapshot_rejects_a_restricted_subscription_context_without_creating_a_run(self) -> None:
        subscription = self._ai_sub_with_contexts(self.restricted_insight)
        self._enable_snapshot(subscription.id)
        snapshot_input = self._snapshot_input([{"insight_id": self.restricted_insight.id}])

        with self.assertRaises(PulseSubscriptionNotFound):
            create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription.id,
                snapshot_input=snapshot_input,
            )

        assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    def test_snapshot_rejects_an_actor_without_subscription_resource_access(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._enable_snapshot(subscription.id)
        self._rule("query")
        snapshot_input = self._snapshot_input([{"insight_id": self.open_insight.id}])

        with self.assertRaises(PulseSubscriptionNotFound):
            create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription.id,
                snapshot_input=snapshot_input,
            )

        assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    def test_snapshot_rejects_an_inactive_actor_without_creating_a_run(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._enable_snapshot(subscription.id)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        snapshot_input = self._snapshot_input([{"insight_id": self.open_insight.id}])

        with self.assertRaises(PulseSubscriptionNotFound):
            create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription.id,
                snapshot_input=snapshot_input,
            )

        assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    def test_snapshot_rejects_contexts_that_do_not_belong_to_the_subscription(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._enable_snapshot(subscription.id)
        other_insight = self.open_insight.__class__.objects.create(
            team=self.team,
            filters={"events": [{"id": "$pageview"}]},
        )
        snapshot_input = self._snapshot_input([{"insight_id": other_insight.id}])

        with self.assertRaises(PulseSubscriptionNotFound):
            create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription.id,
                snapshot_input=snapshot_input,
            )

        assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    def test_history_allows_an_accessible_immutable_context(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_history_hides_a_run_with_a_now_restricted_snapshot_context(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        self._run_for(subscription.id, [{"insight_id": self.restricted_insight.id}])

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_history_projects_safe_recommendation_and_readout_cards(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        action = self._action_for(run)
        plan = self._plan_for(action)
        plan.measurement_spec = {"arguments": {"private": "must not ship"}, "version": 1}
        plan.save(update_fields=["measurement_spec", "updated_at"])
        OutcomeObservation.objects.for_team(self.team.id).create(
            team=self.team,
            plan=plan,
            run=run,
            attempt_number=1,
            status=OutcomeObservation.Status.FAILED,
            verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
            failure_code="provider_unavailable",
        )
        OutcomeObservation.objects.for_team(self.team.id).create(
            team=self.team,
            plan=plan,
            run=run,
            attempt_number=2,
            status=OutcomeObservation.Status.MEASURED,
            observed_value=12,
            absolute_delta=2,
            relative_delta=20,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        history = response.json()[0]
        assert history["actions"][0]["baseline_value"] == "10.00"
        assert history["actions"][0]["adoption_status"] == "pending"
        assert history["readouts"][0]["recommendation_title"] == "Title"
        assert history["readouts"][0]["metric_name"] == "Count"
        assert history["readouts"][0]["metric_unit"] == "count"
        assert history["readouts"][0]["verdict"] == "improved"
        assert len(history["readouts"]) == 1
        assert "measurement_spec" not in response.content.decode()
        assert "must not ship" not in response.content.decode()

    def test_history_omits_readout_from_a_restricted_source_snapshot(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        source_run = self._run_for(subscription.id, [{"insight_id": self.restricted_insight.id}])
        action = self._action_for(source_run)
        plan = self._plan_for(action)
        source_run.status = PulseRun.Status.COMPLETED
        source_run.save(update_fields=["status", "updated_at"])
        measurement_run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        OutcomeObservation.objects.for_team(self.team.id).create(
            team=self.team,
            plan=plan,
            run=measurement_run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["id"] == str(measurement_run.id)
        assert response.json()[0]["readouts"] == []

    def test_history_caps_readouts_after_authorizing_source_snapshots(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        plans: list[OutcomePlan] = []
        for index in range(1, 5):
            contexts = [{"insight_id": self.open_insight.id if index == 4 else self.restricted_insight.id}]
            source_run = self._run_for(subscription.id, contexts)
            action = self._action_for(source_run, index=index)
            plans.append(self._plan_for(action))
            source_run.status = PulseRun.Status.COMPLETED
            source_run.save(update_fields=["status", "updated_at"])

        measurement_run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        for plan in plans:
            OutcomeObservation.objects.for_team(self.team.id).create(
                team=self.team,
                plan=plan,
                run=measurement_run,
                attempt_number=1,
                status=OutcomeObservation.Status.MEASURED,
                verdict=OutcomeObservation.Verdict.IMPROVED,
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        measurement_history = next(run for run in response.json() if run["id"] == str(measurement_run.id))
        assert [readout["recommendation_title"] for readout in measurement_history["readouts"]] == ["Title"]

    def test_decision_denies_an_action_with_a_restricted_snapshot_context(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.restricted_insight.id}]))
        self._plan_for(action)

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        action.refresh_from_db()
        assert action.acted_on is False

    def test_history_denies_a_restricted_current_insight_context(self) -> None:
        subscription = self._ai_sub_with_contexts(self.restricted_insight)

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_history_denies_a_restricted_dashboard_context_and_blocked_tile(self) -> None:
        subscription = self._ai_sub_with_contexts(self.restricted_dashboard)
        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        dashboard = self._dashboard_with_tiles(self.restricted_insight)
        subscription = self._ai_sub_with_contexts(dashboard)
        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_decision_adopts_advice_only_recommendation_through_the_endpoint(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        plan = self._plan_for(action)

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["plan_id"] == str(plan.id)
        assert response.json()["action_id"] == str(action.id)
        assert response.json()["adoption_status"] == "adopted"
        assert response.json()["readout_status"] == "scheduled"
        assert response.json()["decided_by_id"] == self.user.id
        action.refresh_from_db()
        assert action.acted_on is False
        assert action.acted_on_by_id is None
        assert action.acted_on_at is None

    def test_decision_allows_manual_reversal_before_measurement(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        plan = self._plan_for(action)

        adopted = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )
        dismissed = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "dismissed"}
        )

        assert adopted.status_code == status.HTTP_200_OK
        assert dismissed.status_code == status.HTTP_200_OK
        assert dismissed.json()["decision_at"] != adopted.json()["decision_at"]
        plan.refresh_from_db()
        assert plan.adoption_status == OutcomePlan.AdoptionStatus.DISMISSED
        assert plan.readout_status == OutcomePlan.ReadoutStatus.CANCELLED

    def test_decision_rejects_a_measured_recommendation(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        plan = self._plan_for(action)
        OutcomeObservation.objects.for_team(self.team.id).create(
            team=self.team,
            plan=plan,
            run=action.run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )
        plan.adoption_status = OutcomePlan.AdoptionStatus.ADOPTED
        plan.readout_status = OutcomePlan.ReadoutStatus.MEASURED
        plan.save(update_fields=["adoption_status", "readout_status", "updated_at"])

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "dismissed"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_decision_rejects_a_changed_decision_while_measuring(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        plan = self._plan_for(action)
        adopted = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )
        plan.readout_status = OutcomePlan.ReadoutStatus.MEASURING
        plan.claimed_by_run = action.run
        plan.claimed_at = timezone.now()
        plan.save(update_fields=["readout_status", "claimed_by_run", "claimed_at", "updated_at"])

        dismissed = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "dismissed"}
        )

        assert adopted.status_code == status.HTTP_200_OK
        assert dismissed.status_code == status.HTTP_400_BAD_REQUEST
        plan.refresh_from_db()
        assert plan.claimed_by_run_id == action.run_id

    def test_decision_retries_the_same_adoption_after_measurement(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        plan = self._plan_for(action)
        first = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )
        OutcomeObservation.objects.for_team(self.team.id).create(
            team=self.team,
            plan=plan,
            run=action.run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )
        plan.readout_status = OutcomePlan.ReadoutStatus.MEASURED
        plan.save(update_fields=["readout_status", "updated_at"])

        retry = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )

        assert first.status_code == retry.status_code == status.HTTP_200_OK
        assert retry.json()["decision_at"] == first.json()["decision_at"]
        assert retry.json()["adopted_at"] == first.json()["adopted_at"]
        assert retry.json()["decided_by_id"] == first.json()["decided_by_id"]

    def test_decision_rejects_artifact_backed_actions(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        self._plan_for(action)
        Artifact.objects.for_team(self.team.id).create(
            team=self.team,
            run=action.run,
            action=action,
            opportunity=action.opportunity,
            proposal=action.proposal,
            kind=Artifact.Kind.DRAFT_PR,
            idempotency_key=f"decision-artifact:{action.id}",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_decision_double_submit_is_idempotent(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        action = self._action_for(self._run_for(subscription.id, [{"insight_id": self.open_insight.id}]))
        self._plan_for(action)

        first = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )
        second = self.client.post(
            f"/api/projects/{self.team.id}/subscriptions/pulse/actions/{action.id}/decision/", {"decision": "adopted"}
        )

        assert first.status_code == second.status_code == status.HTTP_200_OK
        assert second.json() == first.json()

    def test_cross_team_identifiers_do_not_leak(self) -> None:
        other_team = self.team.__class__.objects.create(organization=self.organization, name="Other team")
        response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id=999999")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert other_team.id != self.team.id

    @override_settings(PULSE_DRAFT_PR_ENABLED=True)
    def test_proactive_draft_pr_creates_reuses_and_revokes_a_server_managed_grant(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        binding = AuthorizableRepositoryDTO(
            repository="PostHog/posthog",
            github_integration_id=13,
            github_installation_id="installation-13",
        )
        config_input = ProactiveConfigInput(
            enabled=True,
            repository="posthog/posthog",
            repository_integration_id=13,
            create_draft_pr=True,
        )

        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=binding,
            create=True,
        ):
            first = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id,
                resource_type="ai_prompt",
                config=config_input,
            )
            second = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id,
                resource_type="ai_prompt",
                config=config_input,
            )

        assert first.repository_grant_id is not None
        assert second.repository_grant_id == first.repository_grant_id
        grant = RepositoryGrant.objects.for_team(self.team.id).get(id=first.repository_grant_id)
        assert grant.repository == "posthog/posthog"
        assert grant.grant_version == 1
        assert grant.authorizer_id == self.user.id
        assert grant.automation_owner_id == self.user.id

        rotated_binding = AuthorizableRepositoryDTO(
            repository="PostHog/posthog",
            github_integration_id=14,
            github_installation_id="installation-14",
        )
        rotated_input = ProactiveConfigInput(
            enabled=True,
            repository="posthog/posthog",
            repository_integration_id=14,
            create_draft_pr=True,
        )
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=rotated_binding,
            create=True,
        ):
            rotated = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id,
                resource_type="ai_prompt",
                config=rotated_input,
            )
        assert rotated.repository_grant_id is not None
        assert rotated.repository_grant_id != first.repository_grant_id
        grant.refresh_from_db()
        replacement = RepositoryGrant.objects.for_team(self.team.id).get(id=rotated.repository_grant_id)
        assert grant.active is False
        assert replacement.active is True
        assert replacement.grant_version == 2

        disabled = configure_proactive_subscription(
            team_id=self.team.id,
            subscription_id=subscription.id,
            current_user_id=self.user.id,
            resource_type="ai_prompt",
            config=ProactiveConfigInput(enabled=True, create_draft_pr=False),
        )
        replacement.refresh_from_db()
        assert disabled.enabled is True
        assert disabled.create_draft_pr is False
        assert disabled.repository is None
        assert disabled.repository_grant_id is None
        assert (
            RepositoryGrant.objects.for_team(self.team.id)
            .filter(id=replacement.id, active=False, revoked_at__isnull=False)
            .exists()
        )

    @override_settings(PULSE_DRAFT_PR_ENABLED=True)
    def test_disabling_draft_pr_cancels_the_matching_active_staged_task_after_commit(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        binding = AuthorizableRepositoryDTO(
            repository="PostHog/posthog",
            github_integration_id=13,
            github_installation_id="installation-13",
        )
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=binding,
        ):
            configured = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id,
                resource_type="ai_prompt",
                config=ProactiveConfigInput(
                    enabled=True,
                    repository="posthog/posthog",
                    repository_integration_id=13,
                    create_draft_pr=True,
                ),
            )

        assert configured.repository_grant_id is not None
        run = PulseRun.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=subscription.id,
            delivery_id=uuid4(),
            status=PulseRun.Status.EXECUTING,
            config_snapshot={"repository_grant": {"id": str(configured.repository_grant_id)}},
            report_snapshot_ref="reports/test",
            task_id=uuid4(),
            analysis_task_run_id=uuid4(),
            execution_task_run_id=uuid4(),
        )

        with (
            patch(
                "products.subscriptions.backend.facade.pulse.tasks_api.revoke_staged_task_capabilities"
            ) as revoke_staged_task_capabilities,
            patch("products.subscriptions.backend.facade.pulse.tasks_api.cancel_staged_task") as cancel_staged_task,
        ):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                configure_proactive_subscription(
                    team_id=self.team.id,
                    subscription_id=subscription.id,
                    current_user_id=self.user.id,
                    resource_type="ai_prompt",
                    config=ProactiveConfigInput(enabled=True, create_draft_pr=False),
                )

            run.refresh_from_db()
            assert run.cancellation_requested_at is not None
            revoke_staged_task_capabilities.assert_called_once()
            revoke_input = revoke_staged_task_capabilities.call_args.args[0]
            assert revoke_input.team_id == self.team.id
            assert revoke_input.caller_id == run.id
            assert revoke_input.task_id == run.task_id
            assert revoke_input.source_run_id == run.analysis_task_run_id
            cancel_staged_task.assert_not_called()
            for callback in callbacks:
                callback()

        cancel_staged_task.assert_called_once()
        cancel_input = cancel_staged_task.call_args.args[0]
        assert cancel_input.team_id == self.team.id
        assert cancel_input.caller_id == run.id
        assert cancel_input.task_id == run.task_id
        assert cancel_input.source_run_id == run.analysis_task_run_id

    @override_settings(PULSE_DRAFT_PR_ENABLED=True)
    def test_proactive_draft_pr_does_not_accept_another_editor_or_client_selected_grant(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=None,
            create=True,
        ):
            with self.assertRaises(PulseValidationError) as error:
                configure_proactive_subscription(
                    team_id=self.team.id,
                    subscription_id=subscription.id,
                    current_user_id=self.user.id + 1,
                    resource_type="ai_prompt",
                    config=ProactiveConfigInput(
                        enabled=True,
                        repository="posthog/posthog",
                        repository_integration_id=13,
                        create_draft_pr=True,
                    ),
                )

        assert "repository" in error.exception.errors
        assert (
            not RepositoryGrant.objects.for_team(self.team.id).filter(config__subscription_id=subscription.id).exists()
        )

    @override_settings(PULSE_DRAFT_PR_ENABLED=True)
    def test_proactive_draft_pr_preserves_an_unchanged_grant_for_another_editor(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        binding = AuthorizableRepositoryDTO(
            repository="PostHog/posthog",
            github_integration_id=13,
            github_installation_id="installation-13",
        )
        config_input = ProactiveConfigInput(
            enabled=True,
            repository="posthog/posthog",
            repository_integration_id=13,
            create_draft_pr=True,
        )
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=binding,
        ):
            configured = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id,
                resource_type="ai_prompt",
                config=config_input,
            )

        with patch("products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization") as resolve:
            preserved = configure_proactive_subscription(
                team_id=self.team.id,
                subscription_id=subscription.id,
                current_user_id=self.user.id + 1,
                resource_type="ai_prompt",
                config=config_input,
            )

        assert preserved.repository_grant_id == configured.repository_grant_id
        resolve.assert_not_called()
        assert configured.repository_grant_id is not None
        grant = RepositoryGrant.objects.for_team(self.team.id).get(id=configured.repository_grant_id)
        assert grant.authorizer_id == self.user.id
        assert grant.automation_owner_id == self.user.id

    @override_settings(PULSE_PROACTIVE_ENABLED=False, PULSE_PUBLIC_RESEARCH_ENABLED=True)
    def test_proactive_configuration_options_are_dark_while_master_flag_is_off(self) -> None:
        options = get_proactive_configuration_options(team_id=self.team.id, user=self.user)

        assert options.proactive_available is False
        assert options.draft_pr_available is False
        assert options.repositories == []
        assert options.public_research_available is False

    def test_public_research_opt_out_clears_the_legacy_subject_for_older_workers(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        subject = PublicResearchSubject.objects.for_team(self.team.id).create(
            team=self.team,
            name="Legacy subject",
            canonical_domain="example.com",
        )
        ProactiveSubscriptionConfig.objects.for_team(self.team.id).create(
            team=self.team,
            subscription_id=subscription.id,
            enabled=True,
            public_research_enabled=True,
            public_research_subject=subject,
        )

        configure_proactive_subscription(
            team_id=self.team.id,
            subscription_id=subscription.id,
            current_user_id=self.user.id,
            resource_type="ai_prompt",
            config=ProactiveConfigInput(enabled=True, public_research_enabled=False),
        )

        stored = ProactiveSubscriptionConfig.objects.for_team(self.team.id).get(subscription_id=subscription.id)
        assert stored.public_research_subject_id is None

    @override_settings(PULSE_PROACTIVE_ENABLED=True, PULSE_DRAFT_PR_ENABLED=False)
    def test_proactive_configuration_options_do_not_offer_draft_pr_when_its_kill_switch_is_off(self) -> None:
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.list_authorizable_repositories",
            return_value=[
                SimpleNamespace(
                    repository="posthog/posthog",
                    github_integration_id=13,
                    github_installation_id="installation-13",
                )
            ],
            create=True,
        ):
            options = get_proactive_configuration_options(team_id=self.team.id, user=self.user)

        assert options.proactive_available is True
        assert options.draft_pr_available is False
        assert options.repositories == []

    @override_settings(PULSE_PROACTIVE_ENABLED=True, PULSE_DRAFT_PR_ENABLED=False)
    def test_draft_pr_consent_is_rejected_when_its_kill_switch_is_off_but_existing_consent_can_be_disabled(
        self,
    ) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        binding = SimpleNamespace(
            repository="PostHog/posthog",
            github_integration_id=13,
            github_installation_id="installation-13",
        )
        draft_config = ProactiveConfigInput(
            enabled=True,
            repository="posthog/posthog",
            repository_integration_id=13,
            create_draft_pr=True,
        )

        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
            return_value=binding,
        ):
            with self.assertRaises(PulseValidationError) as error:
                configure_proactive_subscription(
                    team_id=self.team.id,
                    subscription_id=subscription.id,
                    current_user_id=self.user.id,
                    resource_type="ai_prompt",
                    config=draft_config,
                )

        assert "create_draft_pr" in error.exception.errors
        assert (
            not RepositoryGrant.objects.for_team(self.team.id).filter(config__subscription_id=subscription.id).exists()
        )

        with override_settings(PULSE_DRAFT_PR_ENABLED=True):
            with patch(
                "products.subscriptions.backend.facade.pulse.tasks_api.resolve_repository_authorization",
                return_value=binding,
            ):
                configure_proactive_subscription(
                    team_id=self.team.id,
                    subscription_id=subscription.id,
                    current_user_id=self.user.id,
                    resource_type="ai_prompt",
                    config=draft_config,
                )

        preserved = configure_proactive_subscription(
            team_id=self.team.id,
            subscription_id=subscription.id,
            current_user_id=self.user.id,
            resource_type="ai_prompt",
            config=draft_config,
        )
        assert preserved.create_draft_pr is True

        disabled = configure_proactive_subscription(
            team_id=self.team.id,
            subscription_id=subscription.id,
            current_user_id=self.user.id,
            resource_type="ai_prompt",
            config=ProactiveConfigInput(enabled=False, create_draft_pr=False),
        )

        assert disabled.enabled is False
        assert disabled.create_draft_pr is False
        assert disabled.repository_grant_id is None

    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_DRAFT_PR_ENABLED=True,
        PULSE_PUBLIC_RESEARCH_ENABLED=True,
        FIRECRAWL_API_KEY="test-firecrawl-key",
    )
    def test_proactive_configuration_options_only_expose_safe_authorized_options(self) -> None:
        authorizations = [
            AuthorizableRepositoryDTO(
                repository="posthog/posthog",
                github_integration_id=13,
                github_installation_id="installation-13",
            )
        ]
        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.list_authorizable_repositories",
            return_value=authorizations,
            create=True,
        ):
            options = get_proactive_configuration_options(team_id=self.team.id, user=self.user)
            response = self.client.get(f"/api/projects/{self.team.id}/subscriptions/pulse/configuration-options/")

        assert options.proactive_available is True
        assert options.draft_pr_available is True
        assert [(option.repository, option.repository_integration_id) for option in options.repositories] == [
            ("posthog/posthog", 13)
        ]
        assert options.public_research_available is True
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "proactive_available": True,
            "draft_pr_available": True,
            "repositories": [{"repository": "posthog/posthog", "repository_integration_id": 13}],
            "public_research_available": True,
        }

    @override_settings(
        PULSE_PROACTIVE_ENABLED=True,
        PULSE_PUBLIC_RESEARCH_ENABLED=True,
        FIRECRAWL_API_KEY="",
    )
    def test_public_research_is_unavailable_without_a_provider_key(self) -> None:
        options = get_proactive_configuration_options(team_id=self.team.id, user=self.user)

        assert options.public_research_available is False

    def test_history_excludes_storage_references_and_unvalidated_artifact_urls(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        action = self._action_for(run)
        Artifact.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            action=action,
            opportunity=action.opportunity,
            proposal=action.proposal,
            kind=Artifact.Kind.DRAFT_PR,
            idempotency_key="history-unsafe-url",
            status=Artifact.Status.VERIFIED,
            external_id="42",
            external_url="https://untrusted.example/pull/42",
            failure_code="none",
        )
        DeliveryLedger.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            destination="email",
            logical_key=f"history:{run.id}:email",
            provider_idempotency_key=f"history:{run.id}:email",
            status=DeliveryLedger.Status.FAILED,
            failure_code="provider_unavailable",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        history = response.json()[0]
        assert "report_snapshot_ref" not in history
        assert history["deliveries"] == [
            {"status": "failed", "failure_code": "provider_unavailable", "accepted_at": None}
        ]
        assert history["actions"][0]["artifacts"][0]["external_url"] is None
        assert history["actions"][0]["build_test_gate"] is None

    def test_history_exposes_only_authoritative_publication_gate_results(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        run.task_id = uuid4()
        run.analysis_task_run_id = uuid4()
        run.execution_task_run_id = uuid4()
        run.save(update_fields=["task_id", "analysis_task_run_id", "execution_task_run_id", "updated_at"])
        action = self._action_for(run)
        lease_id = uuid4()
        Artifact.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            action=action,
            opportunity=action.opportunity,
            proposal=action.proposal,
            kind=Artifact.Kind.DRAFT_PR,
            idempotency_key="history-gate",
            status=Artifact.Status.CREATING,
            task_id=run.task_id,
            execution_task_run_id=run.execution_task_run_id,
            publication_lease_id=lease_id,
        )
        completed_at = timezone.now()
        publication = StagedDraftPublicationDTO(
            status="finalized",
            pr_number=42,
            pr_url="https://github.com/PostHog/posthog/pull/42",
            gate_status="passed",
            gate_completed_at=completed_at,
            gates=(
                PublicationGateDTO(label="Focused tests", status="passed"),
                PublicationGateDTO(label="Frontend build", status="passed"),
            ),
        )

        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.get_staged_draft_publication",
            return_value=publication,
        ) as get_publication:
            response = self.client.get(
                f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()[0]["actions"][0]["build_test_gate"] == {
            "status": "passed",
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
            "failure_code": None,
            "gates": [
                {"label": "Focused tests", "status": "passed"},
                {"label": "Frontend build", "status": "passed"},
            ],
        }
        request = get_publication.call_args.args[0]
        assert request.team_id == self.team.id
        assert request.caller_id == run.id
        assert request.task_id == run.task_id
        assert request.source_run_id == run.analysis_task_run_id
        assert request.execution_run_id == run.execution_task_run_id
        assert request.publication_lease_id == lease_id

    def test_history_exposes_only_verified_public_research_citation_fields(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        run = self._run_for(subscription.id, [{"insight_id": self.open_insight.id}])
        action = self._action_for(run)
        call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            tool_call_id="public-research-1",
            tool_name="pulse_public_research",
            tool_schema_version="v1",
            normalized_arguments_ref="sha256:arguments",
            normalized_result_ref="sha256:result",
            actor_id=self.user.id,
            started_at=timezone.now(),
            completed_at=timezone.now(),
            raw_expires_at=timezone.now() + timedelta(days=1),
        )
        EvidenceRawBody.objects.for_team(self.team.id).create(
            team=self.team,
            tool_call=call,
            encrypted_result=(
                '{"canonical_url":"https://example.com/release-notes","title":"Release notes",'
                '"retrieved_at":"2026-08-30T10:00:00+00:00","excerpt":"private evidence"}'
            ),
        )
        evidence_set = EvidenceSet.objects.for_team(self.team.id).create(
            team=self.team,
            run=run,
            content_hash="a" * 64,
            item_refs=[{"tool_call_id": call.tool_call_id}],
        )
        action.evidence_set = evidence_set
        action.save(update_fields=["evidence_set", "updated_at"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/subscriptions/pulse/history/?subscription_id={subscription.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        citation = response.json()[0]["actions"][0]["citations"][0]
        assert citation == {
            "evidence_id": str(call.id),
            "canonical_url": "https://example.com/release-notes",
            "title": "Release notes",
            "retrieved_at": "2026-08-30T10:00:00Z",
        }
        assert "excerpt" not in citation

    def test_history_batches_the_maximum_bounded_shape(self) -> None:
        subscription = self._ai_sub_with_contexts(self.open_insight)
        now = timezone.now()
        for run_index in range(50):
            run = self._run_for(subscription.id, [])
            run.task_id = uuid4()
            run.analysis_task_run_id = uuid4()
            run.execution_task_run_id = uuid4()
            run.status = PulseRun.Status.COMPLETED
            run.save(update_fields=["task_id", "analysis_task_run_id", "execution_task_run_id", "status", "updated_at"])
            for action_index in range(1, 4):
                action = self._action_for(run, index=action_index)
                call = EvidenceToolCall.objects.for_team(self.team.id).create(
                    team=self.team,
                    run=run,
                    tool_call_id=f"public-research-{run_index}-{action_index}",
                    tool_name="pulse_public_research",
                    tool_schema_version="v1",
                    normalized_arguments_ref="sha256:arguments",
                    normalized_result_ref="sha256:result",
                    actor_id=self.user.id,
                    started_at=now,
                    completed_at=now,
                    raw_expires_at=now + timedelta(days=1),
                )
                EvidenceRawBody.objects.for_team(self.team.id).create(
                    team=self.team,
                    tool_call=call,
                    encrypted_result=(
                        '{"canonical_url":"https://example.com/release-notes","title":"Release notes",'
                        '"retrieved_at":"2026-08-30T10:00:00+00:00"}'
                    ),
                )
                evidence_set = EvidenceSet.objects.for_team(self.team.id).create(
                    team=self.team,
                    run=run,
                    content_hash=f"{run_index:02x}{action_index:02x}".ljust(64, "a"),
                    item_refs=[{"tool_call_id": call.tool_call_id}],
                )
                action.evidence_set = evidence_set
                action.save(update_fields=["evidence_set", "updated_at"])
                if action_index == 1:
                    Artifact.objects.for_team(self.team.id).create(
                        team=self.team,
                        run=run,
                        action=action,
                        opportunity=action.opportunity,
                        proposal=action.proposal,
                        kind=Artifact.Kind.DRAFT_PR,
                        idempotency_key=f"history-gate-{run.id}",
                        status=Artifact.Status.CREATING,
                        task_id=run.task_id,
                        execution_task_run_id=run.execution_task_run_id,
                        publication_lease_id=uuid4(),
                    )
            DeliveryLedger.objects.for_team(self.team.id).create(
                team=self.team,
                run=run,
                destination="email",
                logical_key=f"history:{run.id}:email",
                provider_idempotency_key=f"history:{run.id}:email",
            )

        with (
            patch("products.subscriptions.backend.facade.pulse._require_authorized_subscription"),
            patch(
                "products.subscriptions.backend.facade.pulse.tasks_api.get_staged_draft_publication", return_value=None
            ) as get_publication,
            CaptureQueriesContext(connection) as queries,
        ):
            history = list_pulse_history(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                subscription_id=subscription.id,
            )

        assert len(history) == 50
        assert all(len(run.actions) == 3 for run in history)
        assert all(len(run.deliveries) == 1 for run in history)
        assert len(queries) <= 16
        assert get_publication.call_count == 50

    def test_history_bulk_authorizes_maximum_source_snapshots_without_per_observation_queries(self) -> None:
        dashboard = self._dashboard_with_tiles(self.open_insight)
        subscription = self._ai_sub_with_contexts(self.open_insight)
        now = timezone.now()
        for run_index in range(50):
            contexts = [{"dashboard_id": dashboard.id}] if run_index % 2 else [{"insight_id": self.open_insight.id}]
            run = self._run_for(subscription.id, contexts)
            run.status = PulseRun.Status.COMPLETED
            run.save(update_fields=["status", "updated_at"])
            for action_index in range(1, 4):
                action = self._action_for(run, index=action_index)
                plan = self._plan_for(action)
                OutcomeObservation.objects.for_team(self.team.id).create(
                    team=self.team,
                    plan=plan,
                    run=run,
                    attempt_number=1,
                    status=OutcomeObservation.Status.MEASURED,
                    observed_value=12,
                    observed_from=now - timedelta(days=1),
                    observed_to=now,
                    absolute_delta=2,
                    relative_delta=20,
                    verdict=OutcomeObservation.Verdict.IMPROVED,
                )

        with CaptureQueriesContext(connection) as queries:
            history = list_pulse_history(
                team_id=self.team.id,
                team=self.team,
                user=self.user,
                subscription_id=subscription.id,
            )

        assert len(history) == 50
        assert all(len(run.readouts) == 3 for run in history)
        assert len(queries) <= 30
