"""Outcome-plan claiming and terminal measurement behavior."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from products.subscriptions.backend.facade.pulse import purge_expired_evidence_raw_bodies
from products.subscriptions.backend.models import (
    ActionProposal,
    EvidenceRawBody,
    EvidenceSet,
    EvidenceToolCall,
    Opportunity,
    OutcomeObservation,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.subscriptions.backend.pulse.contracts import PulseOutcomeReadoutInput, PulseOutcomeReadoutPersistenceInput
from products.subscriptions.backend.pulse.evidence import evidence_payload_ref, serialize_evidence_payload
from products.subscriptions.backend.pulse.outcomes import (
    PulseOutcomeConflict,
    claim_due_outcomes,
    claim_outcomes_for_run_snapshot,
    persist_outcome_readouts,
)


class TestPulseOutcomes(BaseTest):
    def _readout_run_id(self) -> UUID:
        return (
            PulseRun.objects.for_team(self.team.id)
            .create(
                team_id=self.team.id,
                subscription_id=1,
                delivery_id=uuid4(),
                report_snapshot_ref="readout-report",
                config_snapshot={"actor_id": self.user.id},
            )
            .id
        )

    def _plan(self, *, status: str = OutcomePlan.ReadoutStatus.DUE, suffix: str = "") -> OutcomePlan:
        run = PulseRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            subscription_id=1,
            delivery_id=uuid4(),
            report_snapshot_ref="report",
            config_snapshot={"actor_id": self.user.id},
            status=PulseRun.Status.COMPLETED,
        )
        opportunity = Opportunity.objects.for_team(self.team.id).create(
            team_id=self.team.id, stable_key=f"checkout{suffix}", title="Checkout", summary="Checkout declined"
        )
        proposal = ActionProposal.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            opportunity=opportunity,
            stable_action_key=f"checkout-rate{suffix}",
            kind=ActionProposal.Kind.RECOMMENDATION,
            normalized_target={"area": "checkout"},
        )
        action = RunAction.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"checkout-rate{suffix}",
            kind=RunAction.Kind.RECOMMENDATION,
            title="Improve checkout",
            rationale="The rate declined",
            expected_impact="More purchases",
            why_now="The decline is recent",
            confidence=0.8,
            effort="small",
            metric_name="Checkout completion",
            metric_unit=RunAction.MetricUnit.PERCENT,
            metric_direction=RunAction.MetricDirection.INCREASE,
            expected_change_type=RunAction.ExpectedChangeType.ABSOLUTE,
            expected_change_lower=Decimal("1"),
            expected_change_upper=Decimal("3"),
            readout_after_days=7,
            rank=1,
        )
        return OutcomePlan.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            subscription_id=1,
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
                },
                "selector": {},
                "extraction_kind": "metric_count",
            },
            baseline_value=Decimal("10"),
            baseline_from=datetime(2026, 1, 1, tzinfo=UTC),
            baseline_to=datetime(2026, 1, 8, tzinfo=UTC),
            adoption_status=OutcomePlan.AdoptionStatus.ADOPTED,
            readout_status=status,
            next_readout_at=datetime(2026, 1, 15, tzinfo=UTC),
        )

    def test_claim_binds_one_due_plan_without_incrementing_attempts(self) -> None:
        plan = self._plan()
        now = datetime(2026, 1, 15, tzinfo=UTC)
        run_id = self._readout_run_id()

        claimed = claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=3)

        assert [item.plan_id for item in claimed] == [plan.id]
        plan.refresh_from_db()
        assert plan.readout_status == OutcomePlan.ReadoutStatus.MEASURING
        assert plan.claimed_by_run_id == run_id
        assert plan.attempt_count == 0
        assert claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=3) == ()

    def test_expired_claim_is_reclaimed_by_the_next_run(self) -> None:
        plan = self._plan(status=OutcomePlan.ReadoutStatus.MEASURING)
        plan.claimed_by_run_id = uuid4()
        plan.claimed_at = datetime(2026, 1, 15, tzinfo=UTC)
        plan.save(update_fields=["claimed_by_run", "claimed_at", "readout_status"])

        claimed = claim_due_outcomes(
            team_id=self.team.id,
            subscription_id=1,
            run_id=self._readout_run_id(),
            now=datetime(2026, 1, 15, 2, 1, tzinfo=UTC),
            limit=3,
        )

        assert [item.plan_id for item in claimed] == [plan.id]

    def test_snapshot_claims_are_bounded_and_retry_stable(self) -> None:
        first = self._plan()
        second = self._plan(suffix="-second")
        run_id = self._readout_run_id()
        run = PulseRun.objects.for_team(self.team.id).get(id=run_id)
        run.config_snapshot = {"flags": {"allow_outcome_readouts": True}, "limits": {"max_due_readouts": 1}}
        run.save(update_fields=["config_snapshot"])

        claims = claim_outcomes_for_run_snapshot(
            team_id=self.team.id, subscription_id=1, run_id=run_id, now=datetime(2026, 1, 15, tzinfo=UTC)
        )
        replay = claim_outcomes_for_run_snapshot(
            team_id=self.team.id, subscription_id=1, run_id=run_id, now=datetime(2026, 1, 16, tzinfo=UTC)
        )

        assert len(claims) == 1
        assert replay == claims
        run.refresh_from_db()
        assert run.config_snapshot["claimed_outcomes"] == [
            {
                "plan_id": str(claims[0].plan_id),
                "source_action_id": str(claims[0].source_action_id),
                "measurement_spec_version": 1,
            }
        ]
        assert {first.id, second.id}.issuperset({claims[0].plan_id})

    def test_terminal_run_cannot_claim_and_strand_a_due_plan(self) -> None:
        plan = self._plan()
        run_id = self._readout_run_id()
        PulseRun.objects.for_team(self.team.id).filter(id=run_id).update(
            status=PulseRun.Status.SKIPPED,
            config_snapshot={"flags": {"allow_outcome_readouts": True}, "limits": {"max_due_readouts": 1}},
        )

        with self.assertRaises(PulseOutcomeConflict):
            claim_outcomes_for_run_snapshot(
                team_id=self.team.id,
                subscription_id=1,
                run_id=run_id,
                now=datetime(2026, 1, 15, tzinfo=UTC),
            )

        plan.refresh_from_db()
        assert plan.readout_status == OutcomePlan.ReadoutStatus.DUE
        assert plan.claimed_by_run_id is None

    @override_settings(PULSE_MAX_DUE_READOUTS_PER_DELIVERY=1)
    def test_snapshot_limit_remains_authoritative_when_live_setting_changes(self) -> None:
        plans = [self._plan(suffix=f"-{index}") for index in range(3)]
        run_id = self._readout_run_id()
        PulseRun.objects.for_team(self.team.id).filter(id=run_id).update(
            config_snapshot={"flags": {"allow_outcome_readouts": True}, "limits": {"max_due_readouts": 2}}
        )

        claims = claim_outcomes_for_run_snapshot(
            team_id=self.team.id,
            subscription_id=1,
            run_id=run_id,
            now=datetime(2026, 1, 15, tzinfo=UTC),
        )

        assert len(claims) == 2
        assert {claim.plan_id for claim in claims} <= {plan.id for plan in plans}

    def test_invalid_readout_rolls_back_only_its_savepoint(self) -> None:
        valid_plan = self._plan(suffix="-valid")
        invalid_plan = self._plan(suffix="-invalid")
        now = datetime(2026, 1, 15, tzinfo=UTC)
        run_id = self._readout_run_id()
        claims = claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=2)
        assert {claim.plan_id for claim in claims} == {valid_plan.id, invalid_plan.id}

        observations = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=run_id,
                now=now,
                readouts=(
                    PulseOutcomeReadoutInput(
                        plan_id=invalid_plan.id,
                        not_ready=True,
                        failure_code="invalid_combination",
                    ),
                    PulseOutcomeReadoutInput(plan_id=valid_plan.id, failure_code="provider_failed"),
                ),
            )
        )

        assert len(observations) == 1
        assert observations[0].plan_id == valid_plan.id
        valid_plan.refresh_from_db()
        invalid_plan.refresh_from_db()
        assert valid_plan.attempt_count == 1
        assert invalid_plan.attempt_count == 0
        assert invalid_plan.readout_status == OutcomePlan.ReadoutStatus.MEASURING

    def test_second_failed_measurement_creates_terminal_inconclusive_observation(self) -> None:
        plan = self._plan()
        now = datetime(2026, 1, 15, tzinfo=UTC)
        first_run_id = self._readout_run_id()
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=first_run_id, now=now, limit=1)
        first = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=first_run_id,
                now=now,
                readouts=(PulseOutcomeReadoutInput(plan_id=plan.id, failure_code="provider_failed"),),
            )
        )
        assert first[0].status == "failed"
        plan.refresh_from_db()
        assert plan.attempt_count == 1
        assert plan.readout_status == OutcomePlan.ReadoutStatus.DUE
        assert plan.next_readout_at == now + timedelta(days=1)
        PulseRun.objects.for_team(self.team.id).filter(id=first_run_id).update(status=PulseRun.Status.COMPLETED)

        second_run_id = self._readout_run_id()
        assert (
            claim_due_outcomes(
                team_id=self.team.id,
                subscription_id=1,
                run_id=second_run_id,
                now=now + timedelta(hours=1),
                limit=1,
            )
            == ()
        )
        retry_at = now + timedelta(days=1)
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=second_run_id, now=retry_at, limit=1)
        second = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=second_run_id,
                now=retry_at,
                readouts=(PulseOutcomeReadoutInput(plan_id=plan.id, failure_code="provider_failed"),),
            )
        )
        assert second[0].status == "inconclusive"
        plan.refresh_from_db()
        assert plan.readout_status == OutcomePlan.ReadoutStatus.INCONCLUSIVE
        assert plan.attempt_count == 2

    def test_not_ready_readout_waits_until_its_retry_time(self) -> None:
        plan = self._plan()
        now = datetime(2026, 1, 15, tzinfo=UTC)
        first_run_id = self._readout_run_id()
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=first_run_id, now=now, limit=1)

        observations = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=first_run_id,
                now=now,
                readouts=(PulseOutcomeReadoutInput(plan_id=plan.id, not_ready=True),),
            )
        )

        assert observations == ()
        plan.refresh_from_db()
        assert plan.readout_status == OutcomePlan.ReadoutStatus.DUE
        assert plan.next_readout_at == now + timedelta(days=1)
        PulseRun.objects.for_team(self.team.id).filter(id=first_run_id).update(status=PulseRun.Status.COMPLETED)
        retry_run_id = self._readout_run_id()
        assert (
            claim_due_outcomes(
                team_id=self.team.id,
                subscription_id=1,
                run_id=retry_run_id,
                now=now + timedelta(hours=12),
                limit=1,
            )
            == ()
        )
        assert [
            item.plan_id
            for item in claim_due_outcomes(
                team_id=self.team.id,
                subscription_id=1,
                run_id=retry_run_id,
                now=now + timedelta(days=1),
                limit=1,
            )
        ] == [plan.id]

    def test_expired_not_ready_readout_records_the_terminal_attempt(self) -> None:
        plan = self._plan()
        now = datetime(2026, 4, 15, tzinfo=UTC)
        run_id = self._readout_run_id()
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=1)

        observations = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=run_id,
                now=now,
                readouts=(PulseOutcomeReadoutInput(plan_id=plan.id, not_ready=True),),
            )
        )

        assert len(observations) == 1
        assert observations[0].attempt_number == 1
        plan.refresh_from_db()
        assert plan.readout_status == OutcomePlan.ReadoutStatus.INCONCLUSIVE
        assert plan.attempt_count == 1

    def test_measured_observation_keeps_exact_evidence_after_raw_purge(self) -> None:
        plan = self._plan()
        now = datetime(2026, 1, 15, tzinfo=UTC)
        raw_expires_at = timezone.now() + timedelta(hours=1)
        run_id = self._readout_run_id()
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=1)
        arguments = {
            "name": "checkout-completion",
            "date_from": "2026-01-08T00:00:00+00:00",
            "date_to": "2026-01-15T00:00:00+00:00",
        }
        result = {
            "status": "approved",
            "is_drifted": False,
            "unit": "count",
            "kind": "EventsNode",
            "results": [{"count": "12"}],
        }
        call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run_id=run_id,
            tool_call_id="measurement",
            tool_name="data-catalog-metric-run",
            tool_schema_version="v1",
            normalized_arguments_ref=evidence_payload_ref(arguments),
            normalized_result_ref=evidence_payload_ref(result),
            actor_id=self.user.id,
            started_at=now,
            completed_at=now,
            raw_expires_at=raw_expires_at,
        )
        EvidenceRawBody.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            tool_call=call,
            encrypted_arguments=serialize_evidence_payload(arguments),
            encrypted_result=serialize_evidence_payload(result),
        )

        persisted = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=run_id,
                now=now,
                readouts=(PulseOutcomeReadoutInput(plan_id=plan.id, evidence_tool_call_id="measurement"),),
            )
        )

        assert len(persisted) == 1
        observation = OutcomeObservation.objects.for_team(self.team.id).get(id=persisted[0].id)
        assert observation.evidence_set_id is not None
        evidence_set = EvidenceSet.objects.for_team(self.team.id).get(id=observation.evidence_set_id)
        assert evidence_set.item_refs == [
            {
                "tool_call_id": "measurement",
                "tool_name": "data-catalog-metric-run",
                "tool_schema_version": "v1",
                "completed_at": now.isoformat(),
                "result_hash": evidence_payload_ref(result),
            }
        ]

        assert purge_expired_evidence_raw_bodies(now=raw_expires_at + timedelta(seconds=1)) == 1
        observation.refresh_from_db()
        evidence_set.refresh_from_db()
        assert observation.evidence_set_id == evidence_set.id
        assert evidence_set.item_refs[0]["result_hash"] == evidence_payload_ref(result)

    def test_terminal_inconclusive_observation_keeps_exact_evidence_after_raw_purge(self) -> None:
        plan = self._plan()
        plan.attempt_count = 1
        plan.save(update_fields=["attempt_count", "updated_at"])
        now = datetime(2026, 1, 15, tzinfo=UTC)
        raw_expires_at = timezone.now() + timedelta(hours=1)
        run_id = self._readout_run_id()
        claim_due_outcomes(team_id=self.team.id, subscription_id=1, run_id=run_id, now=now, limit=1)
        arguments = {
            "name": "checkout-completion",
            "date_from": "2026-01-08T00:00:00+00:00",
            "date_to": "2026-01-15T00:00:00+00:00",
        }
        result = {
            "status": "approved",
            "is_drifted": False,
            "unit": "percent",
            "kind": "EventsNode",
            "results": [{"count": "12"}],
        }
        call = EvidenceToolCall.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run_id=run_id,
            tool_call_id="inconclusive-measurement",
            tool_name="data-catalog-metric-run",
            tool_schema_version="v1",
            normalized_arguments_ref=evidence_payload_ref(arguments),
            normalized_result_ref=evidence_payload_ref(result),
            actor_id=self.user.id,
            started_at=now,
            completed_at=now,
            raw_expires_at=raw_expires_at,
        )
        EvidenceRawBody.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            tool_call=call,
            encrypted_arguments=serialize_evidence_payload(arguments),
            encrypted_result=serialize_evidence_payload(result),
        )

        persisted = persist_outcome_readouts(
            PulseOutcomeReadoutPersistenceInput(
                team_id=self.team.id,
                run_id=run_id,
                now=now,
                readouts=(
                    PulseOutcomeReadoutInput(
                        plan_id=plan.id,
                        evidence_tool_call_id="inconclusive-measurement",
                    ),
                ),
            )
        )

        assert len(persisted) == 1
        observation = OutcomeObservation.objects.for_team(self.team.id).get(id=persisted[0].id)
        assert observation.status == OutcomeObservation.Status.INCONCLUSIVE
        assert observation.evidence_set_id is not None
        evidence_set = EvidenceSet.objects.for_team(self.team.id).get(id=observation.evidence_set_id)
        assert purge_expired_evidence_raw_bodies(now=raw_expires_at + timedelta(seconds=1)) == 1
        observation.refresh_from_db()
        evidence_set.refresh_from_db()
        assert observation.evidence_set_id == evidence_set.id
        assert evidence_set.item_refs[0]["tool_call_id"] == "inconclusive-measurement"
        assert evidence_set.item_refs[0]["result_hash"] == evidence_payload_ref(result)
