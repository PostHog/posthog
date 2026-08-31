import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone

from products.subscriptions.backend.facade.pulse import record_pulse_parent_failure
from products.subscriptions.backend.models import (
    ActionProposal,
    Artifact,
    EvidenceRawBody,
    EvidenceSet,
    EvidenceToolCall,
    Opportunity,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.subscriptions.backend.pulse.contracts import (
    ActionKind,
    PulseAnalysisActionInput,
    PulseAnalysisPersistenceInput,
    PulseRunCreationInput,
)
from products.subscriptions.backend.pulse.orchestration import (
    PulseOrchestrationConflict,
    _json_snapshot,
    bind_pulse_analysis_task,
    bind_pulse_execution_task,
    create_or_reconcile_pulse_run,
    persist_pulse_analysis,
    reconcile_pulse_draft_publication,
    reconcile_pulse_task_terminal_state,
    request_pulse_run_cancellation,
)
from products.subscriptions.backend.pulse.reaper import _reconcile_outcome_plans, reconcile_pulse_runs
from products.subscriptions.backend.pulse.services import stable_action_key
from products.subscriptions.backend.pulse.temporal.inputs import ProactiveDispatchSnapshot, PulseStartInput


@override_settings(
    PULSE_PROACTIVE_ENABLED=True,
    PULSE_DRAFT_PR_ENABLED=True,
    PULSE_EXPERIMENT_DRAFT_ENABLED=True,
)
class TestPulseOrchestration(BaseTest):
    def _creation_input(
        self,
        *,
        delivery_id=None,
        subscription_id: int = 1,
        prompt: str = "Find an improvement.",
        allow_draft_pr: bool = False,
        allow_outcome_readouts: bool = False,
    ) -> PulseRunCreationInput:
        return PulseRunCreationInput(
            team_id=self.team.id,
            subscription_id=subscription_id,
            delivery_id=delivery_id or uuid4(),
            report_snapshot_ref="subscription-delivery/report",
            wall_clock_deadline_at=timezone.now() + timedelta(minutes=60),
            finalization_margin_seconds=300,
            config_snapshot={
                "actor_id": self.user.id,
                "original_prompt": prompt,
                "flags": {
                    "allow_draft_pr": allow_draft_pr,
                    "allow_experiment_draft": True,
                    "allow_outcome_readouts": allow_outcome_readouts,
                },
                "limits": {"max_actions": 3},
            },
        )

    def _attach_metric_evidence(self, *, run: PulseRun, tool_call_id: str) -> None:
        call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            tool_call_id=tool_call_id,
            tool_name="data-catalog-metric-run",
            tool_schema_version="v1",
            normalized_arguments_ref="sha256:" + "a" * 64,
            normalized_result_ref="sha256:" + "b" * 64,
            actor_id=self.user.id,
            completed_at=timezone.now(),
            raw_expires_at=timezone.now() + timedelta(days=1),
        )
        EvidenceRawBody.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            tool_call=call,
            encrypted_arguments=json.dumps(
                {
                    "name": "checkout-completion",
                    "date_from": "2026-01-01T00:00:00+00:00",
                    "date_to": "2026-01-08T00:00:00+00:00",
                }
            ),
            encrypted_result=json.dumps(
                {
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "10"}],
                }
            ),
        )

    def _measurable_action(
        self,
        *,
        key: str,
        opportunity_key: str,
        opportunity_title: str,
        normalized_target: dict[str, str],
        kind: ActionKind = "experiment_draft",
    ) -> PulseAnalysisActionInput:
        return PulseAnalysisActionInput(
            opportunity_key=opportunity_key,
            opportunity_title=opportunity_title,
            opportunity_summary=f"{opportunity_title} summary",
            action_key=key,
            kind=kind,
            title=f"{opportunity_title} action",
            rationale="Recent decline",
            expected_impact="More purchases",
            rank=1,
            normalized_target=normalized_target,
            evidence_tool_call_ids=(key,),
            why_now="Recent decline",
            confidence=Decimal("0.8"),
            effort="small",
            metric_name="Checkout completion",
            metric_unit="percent",
            metric_direction="increase",
            expected_change_type="absolute",
            expected_change_lower=Decimal("1"),
            expected_change_upper=Decimal("3"),
            readout_after_days=7,
            selector={},
            baseline_tool_call_id=key,
        )

    def _persist_measurable_action(
        self, *, run: PulseRun, action: PulseAnalysisActionInput
    ) -> tuple[tuple[UUID, ...], tuple[UUID, ...]]:
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id=action.action_key)
        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key=action.action_key if action.kind != "recommendation" else None,
                actions=(action,),
            )
        )
        return persisted.action_ids, persisted.artifact_ids

    def _bulk_outcome_plans(
        self,
        *,
        run: PulseRun,
        opportunity: Opportunity,
        count: int,
        key_prefix: str,
        readout_status: str,
        now: datetime,
        claimed_at: datetime | None = None,
    ) -> list[OutcomePlan]:
        proposals = [
            ActionProposal(
                team_id=self.team.id,
                opportunity=opportunity,
                stable_action_key=f"{key_prefix}-{index}",
                kind=ActionProposal.Kind.RECOMMENDATION,
                normalized_target={"area": f"{key_prefix}-{index}"},
            )
            for index in range(count)
        ]
        ActionProposal.all_teams.bulk_create(proposals)
        actions = [
            RunAction(
                team_id=self.team.id,
                run=run,
                opportunity=opportunity,
                proposal=proposal,
                action_key=f"{key_prefix}-{index}",
                kind=RunAction.Kind.RECOMMENDATION,
                title="Recommendation",
                rationale="Recent decline",
                expected_impact="More purchases",
                readout_after_days=7,
                rank=index + 2,
            )
            for index, proposal in enumerate(proposals)
        ]
        RunAction.all_teams.bulk_create(actions)
        plans = [
            OutcomePlan(
                team_id=self.team.id,
                subscription_id=run.subscription_id,
                proposal=proposal,
                source_action=action,
                measurement_spec={"version": 1},
                baseline_value=Decimal("10"),
                baseline_from=now - timedelta(days=14),
                baseline_to=now - timedelta(days=7),
                adoption_status=(
                    OutcomePlan.AdoptionStatus.PENDING
                    if readout_status == OutcomePlan.ReadoutStatus.WAITING
                    else OutcomePlan.AdoptionStatus.ADOPTED
                ),
                adoption_source=(
                    None if readout_status == OutcomePlan.ReadoutStatus.WAITING else OutcomePlan.AdoptionSource.MANUAL
                ),
                adopted_at=None if readout_status == OutcomePlan.ReadoutStatus.WAITING else now - timedelta(days=7),
                readout_status=readout_status,
                next_readout_at=(
                    now - timedelta(hours=1) if readout_status == OutcomePlan.ReadoutStatus.SCHEDULED else None
                ),
                claimed_at=claimed_at,
            )
            for proposal, action in zip(proposals, actions, strict=True)
        ]
        OutcomePlan.all_teams.bulk_create(plans)
        return plans

    def test_replay_returns_the_original_run_and_rejects_a_changed_snapshot(self) -> None:
        creation = self._creation_input()

        first = create_or_reconcile_pulse_run(creation)
        replay = create_or_reconcile_pulse_run(creation)

        assert replay.id == first.id
        assert replay.config_snapshot["flags"] == {
            "allow_draft_pr": False,
            "allow_experiment_draft": True,
            "allow_public_research": False,
            "allow_outcome_readouts": False,
        }
        with self.assertRaises(PulseOrchestrationConflict):
            create_or_reconcile_pulse_run(
                self._creation_input(delivery_id=creation.delivery_id, prompt="Take a different action.")
            )

    def test_snapshot_validates_supported_agent_context_window_token_caps(self) -> None:
        snapshot = _json_snapshot(
            {
                "flags": {},
                "limits": {"max_agent_context_tokens": 1_000_000},
            }
        )

        limits = snapshot["limits"]
        assert isinstance(limits, dict)
        assert limits["max_agent_context_tokens"] == 1_000_000
        with self.assertRaisesRegex(PulseOrchestrationConflict, "agent context window"):
            _json_snapshot({"flags": {}, "limits": {"max_agent_context_tokens": 20_000}})

    def test_overlap_is_recorded_as_a_skipped_run(self) -> None:
        first = create_or_reconcile_pulse_run(self._creation_input())

        skipped = create_or_reconcile_pulse_run(self._creation_input())

        assert first.status == PulseRun.Status.PENDING
        assert skipped.status == PulseRun.Status.SKIPPED
        assert skipped.skip_reason == "overlap_active_run"
        assert skipped.failure_code == "overlap_active_run"

    def test_parent_failure_creates_a_terminal_fallback_when_start_did_not_persist_a_run(self) -> None:
        delivery_id = uuid4()
        record_pulse_parent_failure(
            PulseStartInput(
                team_id=self.team.id,
                subscription_id=1,
                delivery_id=delivery_id,
                report_snapshot_ref=f"subscription-delivery:{delivery_id}",
                proactive_snapshot=ProactiveDispatchSnapshot(
                    version=1,
                    enabled=True,
                    config_snapshot_ref="missing-dispatch-snapshot",
                    wall_clock_budget_seconds=600,
                    finalization_margin_seconds=60,
                ),
            ),
            "pulse_child_failed",
        )

        run = PulseRun.objects.for_team(self.team.id).get(delivery_id=delivery_id)
        assert run.status == PulseRun.Status.SKIPPED
        assert run.failure_code == "pulse_child_failed"

    @patch("products.subscriptions.backend.pulse.orchestration.capture_pulse_run_started")
    def test_analysis_start_telemetry_is_emitted_once_after_the_binding_commits(self, capture: Mock) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()

        with self.captureOnCommitCallbacks(execute=True):
            bind_pulse_analysis_task(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
            )
            bind_pulse_analysis_task(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
            )

        capture.assert_called_once_with(team_id=self.team.id, run_id=run.id)

    @patch("products.subscriptions.backend.pulse.orchestration.capture_pulse_run_terminalized")
    def test_recommendation_only_analysis_emits_terminal_telemetry_after_commit(self, capture: Mock) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )

        with self.captureOnCommitCallbacks(execute=True):
            persist_pulse_analysis(
                PulseAnalysisPersistenceInput(
                    team_id=self.team.id,
                    run_id=run.id,
                    task_id=task_id,
                    analysis_task_run_id=analysis_run_id,
                    selected_action_key=None,
                    actions=(),
                )
            )

        capture.assert_called_once_with(team_id=self.team.id, run_id=run.id, status=PulseRun.Status.COMPLETED)

    def test_combined_selected_action_reserves_one_pr_and_one_experiment(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="combined-checkout")

        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="combined-checkout",
                actions=(
                    self._measurable_action(
                        key="combined-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="combined",
                    ),
                ),
            )
        )

        action = RunAction.objects.for_team(self.team.id).get(id=persisted.action_ids[0])
        artifacts = list(Artifact.objects.for_team(self.team.id).filter(run_id=run.id).order_by("kind"))
        assert action.implementation_selected is True
        assert action.status == RunAction.Status.SELECTED
        assert [artifact.kind for artifact in artifacts] == [Artifact.Kind.DRAFT_PR, Artifact.Kind.EXPERIMENT_DRAFT]
        assert artifacts[0].active_claim is True
        assert all(artifact.status == Artifact.Status.RESERVED for artifact in artifacts)

    def test_analysis_binds_only_completed_actor_scoped_evidence_and_replays_exactly(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        first_call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            tool_call_id="evidence:first",
            tool_name="query_insight",
            tool_schema_version="1",
            normalized_arguments_ref="sha256:" + "1" * 64,
            normalized_result_ref="sha256:" + "2" * 64,
            actor_id=self.user.id,
            completed_at=timezone.now(),
        )
        second_call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            tool_call_id="evidence:second",
            tool_name="pulse_public_research",
            tool_schema_version="1",
            normalized_arguments_ref="sha256:" + "3" * 64,
            normalized_result_ref="sha256:" + "4" * 64,
            actor_id=self.user.id,
            completed_at=timezone.now(),
        )
        action = PulseAnalysisActionInput(
            opportunity_key="checkout-dropoff",
            opportunity_title="Checkout drop-off",
            opportunity_summary="Checkout completion has declined.",
            action_key="experiment-checkout",
            kind="experiment_draft",
            title="Measure a checkout improvement",
            rationale="The funnel regression is concentrated at checkout.",
            expected_impact="A measurable checkout improvement.",
            rank=1,
            normalized_target={"area": "checkout"},
            evidence_tool_call_ids=(second_call.tool_call_id, first_call.tool_call_id),
            why_now="The decline is recent.",
            confidence=Decimal("0.8"),
            effort="small",
            metric_name="Checkout completion",
            metric_unit="percent",
            metric_direction="increase",
            expected_change_type="absolute",
            expected_change_lower=Decimal("1"),
            expected_change_upper=Decimal("3"),
            readout_after_days=7,
            selector={},
            baseline_tool_call_id=first_call.tool_call_id,
        )
        persistence = PulseAnalysisPersistenceInput(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
            selected_action_key=action.action_key,
            actions=(action,),
        )

        first = persist_pulse_analysis(persistence)
        replay = persist_pulse_analysis(persistence)

        assert replay == first
        run_action = RunAction.objects.for_team(self.team.id).get(id=first.action_ids[0])
        assert run_action.evidence_set_id is not None
        evidence_set = EvidenceSet.objects.for_team(self.team.id).get(id=run_action.evidence_set_id)
        assert [item["tool_call_id"] for item in evidence_set.item_refs] == [
            first_call.tool_call_id,
            second_call.tool_call_id,
        ]
        assert set(evidence_set.item_refs[0]) == {
            "tool_call_id",
            "tool_name",
            "tool_schema_version",
            "completed_at",
            "result_hash",
        }
        assert EvidenceSet.objects.for_team(self.team.id).filter(run=run).count() == 1

        conflicting_action = replace(action, evidence_tool_call_ids=(first_call.tool_call_id,))
        with self.assertRaises(PulseOrchestrationConflict):
            persist_pulse_analysis(
                PulseAnalysisPersistenceInput(
                    team_id=self.team.id,
                    run_id=run.id,
                    task_id=task_id,
                    analysis_task_run_id=analysis_run_id,
                    selected_action_key=conflicting_action.action_key,
                    actions=(conflicting_action,),
                )
            )

    def test_analysis_rejects_more_than_three_actions(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        actions = tuple(
            PulseAnalysisActionInput(
                opportunity_key=f"opportunity-{index}",
                opportunity_title="A title",
                opportunity_summary="A summary",
                action_key=f"action-{index}",
                kind="recommendation",
                title="A recommendation",
                rationale="Because evidence supports it.",
                expected_impact="Useful result.",
                rank=index,
                normalized_target={},
            )
            for index in range(1, 5)
        )

        with self.assertRaises(PulseOrchestrationConflict):
            persist_pulse_analysis(
                PulseAnalysisPersistenceInput(
                    team_id=self.team.id,
                    run_id=run.id,
                    task_id=task_id,
                    analysis_task_run_id=analysis_run_id,
                    selected_action_key=None,
                    actions=actions,
                )
            )

    def test_outcome_disabled_skips_oversized_action_prose_before_persisting_domain_rows(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id, run_id=run.id, task_id=task_id, analysis_task_run_id=analysis_run_id
        )
        self._attach_metric_evidence(run=run, tool_call_id="oversized-prose")
        action = replace(
            self._measurable_action(
                key="oversized-prose",
                opportunity_key="oversized-prose",
                opportunity_title="Oversized prose",
                normalized_target={"area": "checkout"},
                kind="recommendation",
            ),
            rationale="x" * 4_001,
        )

        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key=None,
                actions=(action,),
            )
        )

        assert persisted.action_ids == ()
        assert Opportunity.objects.for_team(self.team.id).count() == 0
        assert ActionProposal.objects.for_team(self.team.id).count() == 0
        assert RunAction.objects.for_team(self.team.id).count() == 0
        assert Artifact.objects.for_team(self.team.id).count() == 0

    def test_outcome_disabled_skips_oversized_action_mappings_before_persisting_domain_rows(self) -> None:
        for subscription_id, (field_name, value) in enumerate(
            (
                ("normalized_target", {f"target-{index}": "checkout" for index in range(33)}),
                ("selector", {f"selector-{index}": "0" for index in range(33)}),
            ),
            start=2,
        ):
            with self.subTest(field_name=field_name):
                run = create_or_reconcile_pulse_run(self._creation_input(subscription_id=subscription_id))
                task_id = uuid4()
                analysis_run_id = uuid4()
                bind_pulse_analysis_task(
                    team_id=self.team.id, run_id=run.id, task_id=task_id, analysis_task_run_id=analysis_run_id
                )
                tool_call_id = f"oversized-{field_name}"
                self._attach_metric_evidence(run=run, tool_call_id=tool_call_id)
                action = self._measurable_action(
                    key=tool_call_id,
                    opportunity_key=tool_call_id,
                    opportunity_title=f"Oversized {field_name}",
                    normalized_target={"area": "checkout"},
                    kind="recommendation",
                )
                if field_name == "normalized_target":
                    action = replace(action, normalized_target=value)
                else:
                    action = replace(action, selector=value)

                persisted = persist_pulse_analysis(
                    PulseAnalysisPersistenceInput(
                        team_id=self.team.id,
                        run_id=run.id,
                        task_id=task_id,
                        analysis_task_run_id=analysis_run_id,
                        selected_action_key=None,
                        actions=(action,),
                    )
                )

                assert persisted.action_ids == ()
                assert Opportunity.objects.for_team(self.team.id).count() == 0
                assert ActionProposal.objects.for_team(self.team.id).count() == 0
                assert RunAction.objects.for_team(self.team.id).count() == 0
                assert Artifact.objects.for_team(self.team.id).count() == 0

    def test_outcome_disabled_skips_invalid_measurement_metadata_before_persisting_domain_rows(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id, run_id=run.id, task_id=task_id, analysis_task_run_id=analysis_run_id
        )
        self._attach_metric_evidence(run=run, tool_call_id="invalid-readout-window")
        action = replace(
            self._measurable_action(
                key="invalid-readout-window",
                opportunity_key="invalid-readout-window",
                opportunity_title="Invalid readout window",
                normalized_target={"area": "checkout"},
                kind="recommendation",
            ),
            readout_after_days=1,
        )

        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key=None,
                actions=(action,),
            )
        )

        assert persisted.action_ids == ()
        assert Opportunity.objects.for_team(self.team.id).count() == 0
        assert ActionProposal.objects.for_team(self.team.id).count() == 0
        assert RunAction.objects.for_team(self.team.id).count() == 0
        assert Artifact.objects.for_team(self.team.id).count() == 0

    def test_outcome_disabled_persists_bounded_recommendation(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id, run_id=run.id, task_id=task_id, analysis_task_run_id=analysis_run_id
        )
        self._attach_metric_evidence(run=run, tool_call_id="bounded-recommendation")
        action = self._measurable_action(
            key="bounded-recommendation",
            opportunity_key="bounded-recommendation",
            opportunity_title="Bounded recommendation",
            normalized_target={"area": "checkout"},
            kind="recommendation",
        )

        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key=None,
                actions=(action,),
            )
        )

        assert len(persisted.action_ids) == 1
        assert RunAction.objects.for_team(self.team.id).get(id=persisted.action_ids[0]).title == action.title

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_invalid_measurement_does_not_block_a_valid_sibling_or_reserve_an_artifact(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_outcome_readouts=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id, run_id=run.id, task_id=task_id, analysis_task_run_id=analysis_run_id
        )
        for tool_call_id in ("invalid", "valid"):
            call = EvidenceToolCall.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                run=run,
                tool_call_id=tool_call_id,
                tool_name="data-catalog-metric-run",
                tool_schema_version="v1",
                normalized_arguments_ref="sha256:" + "a" * 64,
                normalized_result_ref="sha256:" + "b" * 64,
                actor_id=self.user.id,
                completed_at=timezone.now(),
                raw_expires_at=timezone.now() + timedelta(days=1),
            )
            EvidenceRawBody.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                tool_call=call,
                encrypted_arguments=json.dumps(
                    {
                        "name": "checkout-completion",
                        "date_from": "2026-01-01T00:00:00+00:00",
                        "date_to": "2026-01-08T00:00:00+00:00",
                    }
                ),
                encrypted_result=json.dumps(
                    {
                        "status": "approved",
                        "is_drifted": False,
                        "unit": "count",
                        "kind": "EventsNode",
                        "results": [{"count": "10"}],
                    }
                ),
            )

        def action(*, key: str, rank: int, lower: Decimal, upper: Decimal) -> PulseAnalysisActionInput:
            return PulseAnalysisActionInput(
                opportunity_key="checkout",
                opportunity_title="Checkout",
                opportunity_summary="Checkout declined",
                action_key=key,
                kind="experiment_draft",
                title=key,
                rationale="Recent decline",
                expected_impact="More purchases",
                rank=rank,
                normalized_target={"area": "checkout"},
                evidence_tool_call_ids=(key,),
                why_now="Recent decline",
                confidence=Decimal("0.8"),
                effort="small",
                metric_name="Checkout completion",
                metric_unit="percent",
                metric_direction="increase",
                expected_change_type="absolute",
                expected_change_lower=lower,
                expected_change_upper=upper,
                readout_after_days=7,
                selector={},
                baseline_tool_call_id=key,
            )

        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="invalid",
                actions=(
                    action(key="invalid", rank=1, lower=Decimal("3"), upper=Decimal("1")),
                    action(key="valid", rank=2, lower=Decimal("1"), upper=Decimal("3")),
                ),
            )
        )

        assert len(persisted.action_ids) == 1
        assert OutcomePlan.objects.for_team(self.team.id).count() == 1
        assert Artifact.objects.for_team(self.team.id).count() == 1

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_actions_use_adapter_metric_identity_across_retries(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_outcome_readouts=True))
        task_id = uuid4()
        analysis_task_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_task_run_id,
        )
        action = replace(
            self._measurable_action(
                key="adapter-owned-metric",
                opportunity_key="checkout",
                opportunity_title="Checkout",
                normalized_target={"area": "checkout"},
            ),
            metric_name="Untrusted conversion percentage",
            metric_unit="percent",
        )
        self._attach_metric_evidence(run=run, tool_call_id=action.baseline_tool_call_id)
        persistence = PulseAnalysisPersistenceInput(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_task_run_id,
            selected_action_key=action.action_key,
            actions=(action,),
        )

        first = persist_pulse_analysis(persistence)
        replay = persist_pulse_analysis(
            replace(
                persistence,
                actions=(replace(action, metric_name="Different model label", metric_unit="ratio"),),
            )
        )

        assert replay == first
        persisted = RunAction.objects.for_team(self.team.id).select_related("proposal").get(id=first.action_ids[0])
        assert persisted.metric_name == "Metric checkout-completion"
        assert persisted.metric_unit == RunAction.MetricUnit.COUNT
        assert persisted.proposal.stable_action_key == stable_action_key(
            kind=action.kind,
            normalized_target=action.normalized_target,
            metric_name="catalog:checkout-completion",
        )

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_reworded_cross_subscription_action_reuses_the_semantic_proposal(self) -> None:
        first_run = create_or_reconcile_pulse_run(self._creation_input(subscription_id=21, allow_outcome_readouts=True))
        first_action = self._measurable_action(
            key="first-evidence",
            opportunity_key="checkout-first",
            opportunity_title="First checkout wording",
            normalized_target={"area": "checkout"},
        )
        first_action_ids, first_artifact_ids = self._persist_measurable_action(run=first_run, action=first_action)
        PulseRun.objects.for_team(self.team.id).filter(id=first_run.id).update(status=PulseRun.Status.COMPLETED)

        second_run = create_or_reconcile_pulse_run(
            self._creation_input(subscription_id=22, allow_outcome_readouts=True)
        )
        reworded_action = self._measurable_action(
            key="second-evidence",
            opportunity_key="checkout-reworded",
            opportunity_title="Completely different checkout wording",
            normalized_target={"area": "checkout"},
        )
        second_action_ids, second_artifact_ids = self._persist_measurable_action(run=second_run, action=reworded_action)

        assert len(first_action_ids) == 1
        assert len(first_artifact_ids) == 1
        assert second_action_ids == ()
        assert second_artifact_ids == ()
        assert ActionProposal.objects.for_team(self.team.id).count() == 1
        assert OutcomePlan.objects.for_team(self.team.id).count() == 1
        assert Artifact.objects.for_team(self.team.id).count() == 1

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_all_terminal_states_suppress_through_the_ninety_day_boundary(self) -> None:
        current_time = timezone.now()
        terminal_states = (
            (OutcomePlan.AdoptionStatus.DISMISSED, OutcomePlan.ReadoutStatus.CANCELLED),
            (OutcomePlan.AdoptionStatus.ABANDONED, OutcomePlan.ReadoutStatus.CANCELLED),
            (OutcomePlan.AdoptionStatus.ADOPTED, OutcomePlan.ReadoutStatus.MEASURED),
            (OutcomePlan.AdoptionStatus.ADOPTED, OutcomePlan.ReadoutStatus.INCONCLUSIVE),
        )

        with patch("products.subscriptions.backend.pulse.orchestration.timezone.now", return_value=current_time):
            for index, (adoption_status, readout_status) in enumerate(terminal_states):
                with self.subTest(adoption_status=adoption_status, readout_status=readout_status):
                    target = {"area": f"terminal-{index}"}
                    first_run = create_or_reconcile_pulse_run(
                        self._creation_input(subscription_id=100 + index * 3, allow_outcome_readouts=True)
                    )
                    first_action = self._measurable_action(
                        key=f"terminal-{index}-first",
                        opportunity_key=f"terminal-{index}-first",
                        opportunity_title="First wording",
                        normalized_target=target,
                        kind="recommendation",
                    )
                    first_action_ids, _ = self._persist_measurable_action(run=first_run, action=first_action)
                    assert len(first_action_ids) == 1
                    plan = OutcomePlan.objects.for_team(self.team.id).get(source_action_id=first_action_ids[0])
                    plan.adoption_status = adoption_status
                    plan.readout_status = readout_status
                    plan.completed_at = current_time - timedelta(days=90)
                    plan.save(update_fields=["adoption_status", "readout_status", "completed_at", "updated_at"])

                    boundary_run = create_or_reconcile_pulse_run(
                        self._creation_input(subscription_id=101 + index * 3, allow_outcome_readouts=True)
                    )
                    boundary_action = self._measurable_action(
                        key=f"terminal-{index}-boundary",
                        opportunity_key=f"terminal-{index}-boundary",
                        opportunity_title="Boundary wording",
                        normalized_target=target,
                        kind="recommendation",
                    )
                    boundary_action_ids, _ = self._persist_measurable_action(run=boundary_run, action=boundary_action)
                    assert boundary_action_ids == ()

                    plan.completed_at = current_time - timedelta(days=90, microseconds=1)
                    plan.save(update_fields=["completed_at", "updated_at"])
                    expired_run = create_or_reconcile_pulse_run(
                        self._creation_input(subscription_id=102 + index * 3, allow_outcome_readouts=True)
                    )
                    expired_action = self._measurable_action(
                        key=f"terminal-{index}-expired",
                        opportunity_key=f"terminal-{index}-expired",
                        opportunity_title="Expired wording",
                        normalized_target=target,
                        kind="recommendation",
                    )
                    expired_action_ids, _ = self._persist_measurable_action(run=expired_run, action=expired_action)
                    assert len(expired_action_ids) == 1

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_reserves_capacity_for_due_expired_and_lifecycle_work(self) -> None:
        current_time = timezone.now()
        run = create_or_reconcile_pulse_run(self._creation_input(allow_outcome_readouts=True))
        action = self._measurable_action(
            key="lifecycle-seed",
            opportunity_key="lifecycle-seed",
            opportunity_title="Lifecycle seed",
            normalized_target={"area": "lifecycle-seed"},
            kind="recommendation",
        )
        action_ids, _ = self._persist_measurable_action(run=run, action=action)
        seed_action = RunAction.objects.for_team(self.team.id).select_related("opportunity").get(id=action_ids[0])
        pending = OutcomePlan.objects.for_team(self.team.id).get(source_action=seed_action)
        OutcomePlan.all_teams.filter(id=pending.id).update(updated_at=current_time - timedelta(days=2))
        scheduled = self._bulk_outcome_plans(
            run=run,
            opportunity=seed_action.opportunity,
            count=76,
            key_prefix="scheduled",
            readout_status=OutcomePlan.ReadoutStatus.SCHEDULED,
            now=current_time,
        )
        expired = self._bulk_outcome_plans(
            run=run,
            opportunity=seed_action.opportunity,
            count=1,
            key_prefix="expired",
            readout_status=OutcomePlan.ReadoutStatus.MEASURING,
            now=current_time,
            claimed_at=None,
        )[0]

        changed = _reconcile_outcome_plans(now=current_time, batch_size=100)

        pending.refresh_from_db()
        expired.refresh_from_db()
        assert pending.updated_at == current_time
        assert expired.readout_status == OutcomePlan.ReadoutStatus.DUE
        assert (
            OutcomePlan.all_teams.filter(
                id__in=[plan.id for plan in scheduled], readout_status=OutcomePlan.ReadoutStatus.DUE
            ).count()
            == 57
        )
        assert changed == 58

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_persists_pending_rotation_across_sweeps(self) -> None:
        current_time = timezone.now()
        run = create_or_reconcile_pulse_run(self._creation_input(allow_outcome_readouts=True))
        action = self._measurable_action(
            key="rotation-seed",
            opportunity_key="rotation-seed",
            opportunity_title="Rotation seed",
            normalized_target={"area": "rotation-seed"},
            kind="recommendation",
        )
        action_ids, _ = self._persist_measurable_action(run=run, action=action)
        seed_action = RunAction.objects.for_team(self.team.id).select_related("opportunity").get(id=action_ids[0])
        pending = [OutcomePlan.objects.for_team(self.team.id).get(source_action=seed_action)]
        pending.extend(
            self._bulk_outcome_plans(
                run=run,
                opportunity=seed_action.opportunity,
                count=3,
                key_prefix="rotation",
                readout_status=OutcomePlan.ReadoutStatus.WAITING,
                now=current_time,
            )
        )
        old_time = current_time - timedelta(days=2)
        OutcomePlan.all_teams.filter(id__in=[plan.id for plan in pending]).update(updated_at=old_time)

        for offset in range(len(pending)):
            _reconcile_outcome_plans(now=current_time + timedelta(minutes=offset), batch_size=4)

        assert not OutcomePlan.all_teams.filter(id__in=[plan.id for plan in pending], updated_at__lte=old_time).exists()

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_requires_both_server_switches(self) -> None:
        current_time = timezone.now()
        run = create_or_reconcile_pulse_run(self._creation_input(allow_outcome_readouts=True))
        action = self._measurable_action(
            key="switch-seed",
            opportunity_key="switch-seed",
            opportunity_title="Switch seed",
            normalized_target={"area": "switch-seed"},
            kind="recommendation",
        )
        action_ids, _ = self._persist_measurable_action(run=run, action=action)
        plan = OutcomePlan.objects.for_team(self.team.id).get(source_action_id=action_ids[0])
        old_time = current_time - timedelta(days=2)
        OutcomePlan.all_teams.filter(id=plan.id).update(updated_at=old_time)

        for disabled_settings in (
            {"PULSE_PROACTIVE_ENABLED": False, "PULSE_OUTCOME_READOUT_ENABLED": True},
            {"PULSE_PROACTIVE_ENABLED": True, "PULSE_OUTCOME_READOUT_ENABLED": False},
        ):
            with self.settings(**disabled_settings):
                assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 0
            plan.refresh_from_db()
            assert plan.updated_at == old_time

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_adopts_a_verified_pr_from_attested_merge_time(self) -> None:
        current_time = timezone.now()
        merged_at = current_time - timedelta(days=1)
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True, allow_outcome_readouts=True))
        action = self._measurable_action(
            key="merged-pr",
            opportunity_key="merged-pr",
            opportunity_title="Merged pull request",
            normalized_target={"area": "merged-pr"},
            kind="draft_pr",
        )
        action_ids, artifact_ids = self._persist_measurable_action(run=run, action=action)
        run.refresh_from_db()
        plan = OutcomePlan.objects.for_team(self.team.id).get(source_action_id=action_ids[0])
        artifact = Artifact.objects.for_team(self.team.id).get(id=artifact_ids[0])
        artifact.status = Artifact.Status.VERIFIED
        artifact.task_id = run.task_id
        artifact.execution_task_run_id = uuid4()
        artifact.publication_lease_id = uuid4()
        artifact.save(
            update_fields=[
                "status",
                "task_id",
                "execution_task_run_id",
                "publication_lease_id",
                "updated_at",
            ]
        )

        with patch("products.subscriptions.backend.pulse.outcomes.capture_pulse_outcome") as capture:
            with (
                self.captureOnCommitCallbacks(execute=True),
                patch(
                    "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle",
                    return_value=SimpleNamespace(state="merged", changed_at=merged_at),
                ),
            ):
                _reconcile_outcome_plans(now=current_time, batch_size=100)

        plan.refresh_from_db()
        assert plan.adoption_status == OutcomePlan.AdoptionStatus.ADOPTED
        assert plan.adoption_source == OutcomePlan.AdoptionSource.PULL_REQUEST_MERGED
        assert plan.adopted_at == merged_at
        assert plan.next_readout_at == merged_at + timedelta(days=7)
        capture.assert_called_once_with(
            team_id=self.team.id,
            run_id=run.id,
            event="pulse_outcome_adoption",
            plan_id=plan.id,
            status="adopted",
            delay_days=7,
            source="pull_request_merged",
        )

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_ignores_an_artifact_from_a_different_source_action(self) -> None:
        current_time = timezone.now()
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True, allow_outcome_readouts=True))
        action = self._measurable_action(
            key="old-pr",
            opportunity_key="shared-proposal",
            opportunity_title="Shared proposal",
            normalized_target={"area": "shared-proposal"},
            kind="draft_pr",
        )
        action_ids, artifact_ids = self._persist_measurable_action(run=run, action=action)
        old_action = RunAction.objects.for_team(self.team.id).get(id=action_ids[0])
        plan = OutcomePlan.objects.for_team(self.team.id).get(source_action=old_action)
        replacement_action = RunAction.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            opportunity=old_action.opportunity,
            proposal=old_action.proposal,
            action_key="replacement-pr",
            kind=RunAction.Kind.DRAFT_PR,
            title="Replacement action",
            rationale="Fresh evidence",
            expected_impact="More purchases",
            readout_after_days=7,
            rank=2,
        )
        OutcomePlan.objects.for_team(self.team.id).filter(id=plan.id).update(source_action=replacement_action)
        artifact = Artifact.objects.for_team(self.team.id).get(id=artifact_ids[0])
        artifact.status = Artifact.Status.VERIFIED
        artifact.task_id = run.task_id
        artifact.execution_task_run_id = uuid4()
        artifact.publication_lease_id = uuid4()
        artifact.save()

        with patch(
            "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle",
            return_value=SimpleNamespace(state="merged", changed_at=current_time),
        ) as lifecycle:
            assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 0

        plan.refresh_from_db()
        assert plan.adoption_status == OutcomePlan.AdoptionStatus.PENDING
        lifecycle.assert_not_called()

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_combined_outcome_waits_for_both_exact_artifacts(self) -> None:
        current_time = timezone.now()
        merged_at = current_time - timedelta(days=2)
        launched_at = current_time - timedelta(days=1)
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True, allow_outcome_readouts=True))
        action = self._measurable_action(
            key="combined-adoption",
            opportunity_key="combined-adoption",
            opportunity_title="Combined adoption",
            normalized_target={"area": "combined-adoption"},
            kind="combined",
        )
        action_ids, artifact_ids = self._persist_measurable_action(run=run, action=action)
        run.refresh_from_db()
        plan = OutcomePlan.objects.for_team(self.team.id).get(source_action_id=action_ids[0])
        artifacts = list(Artifact.objects.for_team(self.team.id).filter(id__in=artifact_ids))
        for artifact in artifacts:
            artifact.status = Artifact.Status.VERIFIED
            if artifact.kind == Artifact.Kind.DRAFT_PR:
                artifact.task_id = run.task_id
                artifact.execution_task_run_id = uuid4()
                artifact.publication_lease_id = uuid4()
            else:
                artifact.experiment_id = 54321
            artifact.save()

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle",
                return_value=SimpleNamespace(state="merged", changed_at=merged_at),
            ),
            patch(
                "products.subscriptions.backend.pulse.reaper.experiments_facade.get_pulse_experiment_lifecycle",
                return_value=SimpleNamespace(state="draft", launched_at=None),
            ),
        ):
            assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 0

        plan.refresh_from_db()
        assert plan.adoption_status == OutcomePlan.AdoptionStatus.PENDING

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle",
                return_value=SimpleNamespace(state="merged", changed_at=merged_at),
            ),
            patch(
                "products.subscriptions.backend.pulse.reaper.experiments_facade.get_pulse_experiment_lifecycle",
                return_value=SimpleNamespace(state="running", launched_at=launched_at),
            ),
        ):
            assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 1

        plan.refresh_from_db()
        assert plan.adoption_status == OutcomePlan.AdoptionStatus.ADOPTED
        assert plan.adoption_source == OutcomePlan.AdoptionSource.EXPERIMENT_LAUNCHED
        assert plan.adopted_at == launched_at

    @override_settings(PULSE_OUTCOME_READOUT_ENABLED=True)
    def test_outcome_reaper_abandons_closed_artifacts_with_bounded_reasons(self) -> None:
        current_time = timezone.now()
        cases: tuple[tuple[ActionKind, str, str], ...] = (
            ("draft_pr", "closed", "pull_request_closed"),
            ("experiment_draft", "deleted", "experiment_deleted"),
        )
        for index, (kind, state, reason) in enumerate(cases):
            with self.subTest(kind=kind):
                run = create_or_reconcile_pulse_run(
                    self._creation_input(
                        subscription_id=500 + index,
                        allow_draft_pr=True,
                        allow_outcome_readouts=True,
                    )
                )
                action = self._measurable_action(
                    key=f"abandoned-{index}",
                    opportunity_key=f"abandoned-{index}",
                    opportunity_title="Abandoned artifact",
                    normalized_target={"area": f"abandoned-{index}"},
                    kind=kind,
                )
                action_ids, artifact_ids = self._persist_measurable_action(run=run, action=action)
                run.refresh_from_db()
                plan = OutcomePlan.objects.for_team(self.team.id).get(source_action_id=action_ids[0])
                artifact = Artifact.objects.for_team(self.team.id).get(id=artifact_ids[0])
                artifact.status = Artifact.Status.VERIFIED
                if kind == "draft_pr":
                    artifact.task_id = run.task_id
                    artifact.execution_task_run_id = uuid4()
                    artifact.publication_lease_id = uuid4()
                else:
                    artifact.experiment_id = 12345 + index
                artifact.save()
                facade_path = (
                    "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle"
                    if kind == "draft_pr"
                    else "products.subscriptions.backend.pulse.reaper.experiments_facade.get_pulse_experiment_lifecycle"
                )
                lifecycle = (
                    SimpleNamespace(state=state, changed_at=current_time)
                    if kind == "draft_pr"
                    else SimpleNamespace(state=state, launched_at=None)
                )

                with patch("products.subscriptions.backend.pulse.outcomes.capture_pulse_outcome") as capture:
                    with self.captureOnCommitCallbacks(execute=True), patch(facade_path, return_value=lifecycle):
                        _reconcile_outcome_plans(now=current_time, batch_size=100)

                plan.refresh_from_db()
                assert plan.adoption_status == OutcomePlan.AdoptionStatus.ABANDONED
                assert plan.readout_status == OutcomePlan.ReadoutStatus.CANCELLED
                capture.assert_called_once_with(
                    team_id=self.team.id,
                    run_id=run.id,
                    event="pulse_outcome_adoption",
                    plan_id=plan.id,
                    status="abandoned",
                    source=reason,
                )
                PulseRun.objects.for_team(self.team.id).filter(id=run.id).update(status=PulseRun.Status.COMPLETED)

    def test_cancellation_intent_is_idempotent_and_sets_a_finalization_deadline(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        current_time = timezone.now()

        first = request_pulse_run_cancellation(team_id=self.team.id, run_id=run.id, now=current_time)
        replay = request_pulse_run_cancellation(
            team_id=self.team.id, run_id=run.id, now=current_time + timedelta(minutes=1)
        )

        assert replay.cancellation_requested_at == first.cancellation_requested_at
        assert run.wall_clock_deadline_at is not None
        assert replay.finalization_deadline_at == run.wall_clock_deadline_at - timedelta(minutes=5)

    @override_settings(PULSE_PROACTIVE_ENABLED=False)
    def test_snapshot_cannot_enable_a_server_disabled_capability(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())

        assert run.config_snapshot["flags"]["allow_experiment_draft"] is False

    @override_settings(PULSE_MAX_TEAM_CONCURRENT_RUNS=0)
    def test_team_concurrency_limit_is_a_durable_skip(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())

        assert run.status == PulseRun.Status.SKIPPED
        assert run.skip_reason == "team_concurrency_limit"

    def test_cutoff_refuses_new_analysis_binding(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        run.finalization_deadline_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["finalization_deadline_at"])

        with self.assertRaises(PulseOrchestrationConflict):
            bind_pulse_analysis_task(
                team_id=self.team.id,
                run_id=run.id,
                task_id=uuid4(),
                analysis_task_run_id=uuid4(),
            )

    def test_terminal_cancellation_abandons_an_unbound_pr_reservation(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="draft-checkout")
        persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="draft-checkout",
                actions=(
                    self._measurable_action(
                        key="draft-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="draft_pr",
                    ),
                ),
            )
        )
        run.refresh_from_db()
        run.finalization_deadline_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["finalization_deadline_at"])

        reconciled = reconcile_pulse_task_terminal_state(
            team_id=self.team.id,
            run_id=run.id,
            task_run_id=analysis_run_id,
            task_status="cancelled",
            now=timezone.now(),
        )

        artifact = Artifact.objects.for_team(self.team.id).get(run_id=run.id, kind=Artifact.Kind.DRAFT_PR)
        assert reconciled.status == PulseRun.Status.CANCELLED
        assert artifact.status == Artifact.Status.FAILED
        assert artifact.failure_code == "artifact_creation_abandoned"
        assert artifact.active_claim is False

    def test_reaper_marks_stalled_artifacts_unknown_without_releasing_the_active_claim(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        execution_run_id = uuid4()
        publication_lease_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="draft-checkout")
        persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="draft-checkout",
                actions=(
                    self._measurable_action(
                        key="draft-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="draft_pr",
                    ),
                ),
            )
        )
        bind_pulse_execution_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
            execution_task_run_id=execution_run_id,
            publication_lease_id=publication_lease_id,
        )
        selected_action = RunAction.objects.for_team(self.team.id).get(run_id=run.id)
        assert selected_action.status == RunAction.Status.EXECUTING
        artifact = Artifact.objects.for_team(self.team.id).get(run_id=run.id, kind=Artifact.Kind.DRAFT_PR)
        assert artifact.publication_lease_id == publication_lease_id
        artifact.status = Artifact.Status.CREATING
        artifact.save(update_fields=["status"])
        run.refresh_from_db()
        run.finalization_deadline_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["finalization_deadline_at"])

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run",
                return_value=SimpleNamespace(is_terminal=True, status="completed", task_id=task_id),
            ) as get_task_run,
            patch("products.subscriptions.backend.pulse.reaper.tasks_facade.cancel_staged_task") as cancel_staged_task,
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=1),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        artifact.refresh_from_db()
        run.refresh_from_db()
        selected_action.refresh_from_db()
        assert result.reconciled_count == 1
        assert result.purged_evidence_count == 1
        assert artifact.status == Artifact.Status.PUBLICATION_UNKNOWN
        assert artifact.active_claim is True
        assert run.status == PulseRun.Status.PARTIAL
        assert selected_action.status == RunAction.Status.FAILED
        cancel_staged_task.assert_called_once()
        get_task_run.assert_called_once_with(execution_run_id, team_id=self.team.id)

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_draft_publication",
                return_value=None,
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        artifact.refresh_from_db()
        assert result.reconciled_count == 0
        assert artifact.status == Artifact.Status.PUBLICATION_UNKNOWN
        assert artifact.active_claim is True

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_draft_publication",
                return_value=SimpleNamespace(
                    status="finalized",
                    pr_number=42,
                    pr_url="https://github.com/posthog/posthog/pull/42",
                ),
            ) as get_publication,
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        artifact.refresh_from_db()
        assert result.reconciled_count == 1
        assert str(artifact.status) == "verified"
        assert artifact.external_id == "42"
        assert artifact.active_claim is True
        get_publication.assert_called_once()

    def test_reaper_terminalizes_completed_execution_after_reconciling_finalized_publication(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        execution_run_id = uuid4()
        publication_lease_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="draft-checkout")
        persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="draft-checkout",
                actions=(
                    self._measurable_action(
                        key="draft-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="draft_pr",
                    ),
                ),
            )
        )
        bind_pulse_execution_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
            execution_task_run_id=execution_run_id,
            publication_lease_id=publication_lease_id,
        )

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run",
                return_value=SimpleNamespace(is_terminal=True, status="completed", task_id=task_id),
            ),
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_draft_publication",
                return_value=SimpleNamespace(
                    status="finalized",
                    pr_number=42,
                    pr_url="https://github.com/posthog/posthog/pull/42",
                ),
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        run.refresh_from_db()
        artifact = Artifact.objects.for_team(self.team.id).get(run_id=run.id, kind=Artifact.Kind.DRAFT_PR)
        selected_action = RunAction.objects.for_team(self.team.id).get(run_id=run.id)
        assert result.reconciled_count == 1
        assert run.status == PulseRun.Status.COMPLETED
        assert run.finished_at is not None
        assert artifact.status == Artifact.Status.VERIFIED
        assert artifact.external_id == "42"
        assert artifact.external_url == "https://github.com/posthog/posthog/pull/42"
        assert selected_action.status == RunAction.Status.COMPLETED

    def test_reaper_terminalizes_an_expired_run_before_any_task_is_bound(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        run.finalization_deadline_at = timezone.now() - timedelta(seconds=1)
        run.save(update_fields=["finalization_deadline_at"])

        with patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0):
            result = reconcile_pulse_runs(now=timezone.now())

        run.refresh_from_db()
        assert result.reconciled_count == 1
        assert run.status == PulseRun.Status.CANCELLED
        assert run.failure_code == "finalization_timeout"
        assert run.cancellation_requested_at is not None

    @override_settings(PULSE_MAX_TEAM_CONCURRENT_RUNS=2)
    def test_reaper_rotates_failed_active_candidates_out_of_the_next_batch(self) -> None:
        first = create_or_reconcile_pulse_run(self._creation_input(subscription_id=20))
        second = create_or_reconcile_pulse_run(self._creation_input(subscription_id=21))
        current_time = timezone.now()
        PulseRun.objects.for_team(self.team.id).filter(id=first.id).update(updated_at=current_time - timedelta(hours=2))
        PulseRun.objects.for_team(self.team.id).filter(id=second.id).update(
            updated_at=current_time - timedelta(hours=1)
        )
        attempted_run_ids: list[UUID] = []

        def get_staged_task(input):
            attempted_run_ids.append(input.caller_id)
            if input.caller_id == first.id:
                raise RuntimeError("task lookup unavailable")
            return None

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_task_by_idempotency",
                side_effect=get_staged_task,
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            reconcile_pulse_runs(now=current_time, batch_size=2)
            reconcile_pulse_runs(now=current_time + timedelta(minutes=5), batch_size=2)

        assert attempted_run_ids == [first.id, second.id]

    def test_reaper_leaves_completed_analysis_for_the_workflow_to_persist(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run",
                return_value=SimpleNamespace(is_terminal=True, status="completed", task_id=task_id),
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        run.refresh_from_db()
        assert result.reconciled_count == 0
        assert run.status == PulseRun.Status.ANALYZING
        assert run.finished_at is None

    def test_reaper_recovers_execution_created_before_pulse_binding(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        execution_run_id = uuid4()
        transition_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="experiment-checkout")
        persisted = persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="experiment-checkout",
                actions=(
                    self._measurable_action(
                        key="experiment-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="experiment_draft",
                    ),
                ),
            )
        )
        action = RunAction.objects.for_team(self.team.id).get(id=persisted.action_ids[0])
        discovered = SimpleNamespace(
            task_id=task_id,
            analysis_run_id=analysis_run_id,
            execution_run_id=execution_run_id,
            transition_id=transition_id,
            publication_lease_id=None,
        )

        with (
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_execution_by_idempotency",
                return_value=discovered,
            ) as get_execution,
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run",
                return_value=SimpleNamespace(is_terminal=False, status="running", task_id=task_id),
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        run.refresh_from_db()
        action.refresh_from_db()
        artifact = Artifact.objects.for_team(self.team.id).get(run_id=run.id)
        lookup = get_execution.call_args.args[0]
        assert result.reconciled_count == 0
        assert lookup.idempotency_key == f"pulse:{run.id}:{action.action_key}:execution"
        assert run.execution_task_run_id == execution_run_id
        assert run.status == PulseRun.Status.EXECUTING
        assert action.status == RunAction.Status.EXECUTING
        assert artifact.execution_task_run_id == execution_run_id
        assert artifact.status == Artifact.Status.CREATING

    def test_authoritative_blocked_publication_releases_the_pr_claim(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input(allow_draft_pr=True))
        task_id = uuid4()
        analysis_run_id = uuid4()
        execution_run_id = uuid4()
        publication_lease_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        self._attach_metric_evidence(run=run, tool_call_id="draft-checkout")
        persist_pulse_analysis(
            PulseAnalysisPersistenceInput(
                team_id=self.team.id,
                run_id=run.id,
                task_id=task_id,
                analysis_task_run_id=analysis_run_id,
                selected_action_key="draft-checkout",
                actions=(
                    self._measurable_action(
                        key="draft-checkout",
                        opportunity_key="checkout-dropoff",
                        opportunity_title="Checkout drop-off",
                        normalized_target={"area": "checkout"},
                        kind="draft_pr",
                    ),
                ),
            )
        )
        bind_pulse_execution_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
            execution_task_run_id=execution_run_id,
            publication_lease_id=publication_lease_id,
        )
        run.refresh_from_db()
        artifact = Artifact.objects.for_team(self.team.id).get(run_id=run.id, kind=Artifact.Kind.DRAFT_PR)

        with patch(
            "products.subscriptions.backend.facade.pulse.tasks_api.get_staged_draft_publication",
            return_value=SimpleNamespace(status="blocked", pr_number=None, pr_url=None),
        ):
            reconcile_pulse_draft_publication(team_id=run.team_id, run_id=run.id)

        artifact.refresh_from_db()
        assert artifact.status == Artifact.Status.FAILED
        assert artifact.failure_code == "publication_blocked"
        assert artifact.active_claim is False

    def test_reaper_converges_a_missing_task_after_the_cancellation_grace_period(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        current_time = timezone.now()
        run.finalization_deadline_at = current_time - timedelta(minutes=11)
        run.cancellation_requested_at = current_time - timedelta(minutes=10)
        run.save(update_fields=["finalization_deadline_at", "cancellation_requested_at"])

        with (
            patch("products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run", return_value=None),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=current_time)

        run.refresh_from_db()
        assert result.reconciled_count == 1
        assert run.status == PulseRun.Status.CANCELLED
        assert run.failure_code == "task_missing_after_cancellation"

    def test_reaper_retries_a_persisted_cancellation_request_before_the_deadline(self) -> None:
        run = create_or_reconcile_pulse_run(self._creation_input())
        task_id = uuid4()
        analysis_run_id = uuid4()
        bind_pulse_analysis_task(
            team_id=self.team.id,
            run_id=run.id,
            task_id=task_id,
            analysis_task_run_id=analysis_run_id,
        )
        request_pulse_run_cancellation(team_id=self.team.id, run_id=run.id)

        with (
            patch("products.subscriptions.backend.pulse.reaper.tasks_facade.cancel_staged_task") as cancel_staged_task,
            patch(
                "products.subscriptions.backend.pulse.reaper.tasks_facade.get_task_run",
                return_value=SimpleNamespace(is_terminal=False, status="running", task_id=task_id),
            ),
            patch("products.subscriptions.backend.pulse.reaper.purge_expired_evidence_raw_bodies", return_value=0),
        ):
            result = reconcile_pulse_runs(now=timezone.now())

        assert result.reconciled_count == 0
        cancel_staged_task.assert_called_once()
        cancel_input = cancel_staged_task.call_args.args[0]
        assert cancel_input.team_id == self.team.id
        assert cancel_input.caller_id == run.id
        assert cancel_input.task_id == task_id
        assert cancel_input.source_run_id == analysis_run_id
