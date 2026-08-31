import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from products.subscriptions.backend.models import (
    ActionProposal,
    Opportunity,
    OutcomeObservation,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.subscriptions.backend.pulse.outcome_memory import DEFAULT_OUTCOME_MEMORY_MAX_BYTES, build_outcome_memory


class TestOutcomeMemory(BaseTest):
    def _plan(
        self,
        *,
        subscription_id: int,
        suffix: str,
        adoption_status: str,
        readout_status: str,
        completed_at: datetime | None = None,
    ) -> OutcomePlan:
        run = PulseRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            subscription_id=subscription_id,
            delivery_id=uuid4(),
            report_snapshot_ref=f"subscription:{subscription_id}",
            config_snapshot={},
            status=PulseRun.Status.COMPLETED,
        )
        opportunity = Opportunity.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            stable_key=f"opportunity:{suffix}",
            title="Model title",
            summary="Model summary",
        )
        proposal = ActionProposal.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            opportunity=opportunity,
            stable_action_key=f"action:{suffix}",
            kind=ActionProposal.Kind.RECOMMENDATION,
            normalized_target={"category": "checkout", "credential": "must-not-leak"},
        )
        action = RunAction.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"run-action:{suffix}",
            kind=RunAction.Kind.RECOMMENDATION,
            title="Model title must-not-leak",
            rationale="Model rationale must-not-leak",
            expected_impact="Model impact",
            metric_name="Checkout completion",
            rank=1,
        )
        return OutcomePlan.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            subscription_id=subscription_id,
            proposal=proposal,
            source_action=action,
            measurement_spec={"arguments": "must-not-leak", "result": "must-not-leak"},
            baseline_value=Decimal("10"),
            baseline_from=timezone.now() - timedelta(days=14),
            baseline_to=timezone.now() - timedelta(days=7),
            adoption_status=adoption_status,
            readout_status=readout_status,
            completed_at=completed_at,
        )

    def test_subscription_memory_contains_only_safe_active_and_recent_proposal_metadata(self) -> None:
        now = timezone.now()
        active = self._plan(
            subscription_id=1,
            suffix="active",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )
        recent = self._plan(
            subscription_id=1,
            suffix="recent",
            adoption_status=OutcomePlan.AdoptionStatus.DISMISSED,
            readout_status=OutcomePlan.ReadoutStatus.CANCELLED,
            completed_at=now - timedelta(days=1),
        )
        old = self._plan(
            subscription_id=1,
            suffix="old",
            adoption_status=OutcomePlan.AdoptionStatus.ADOPTED,
            readout_status=OutcomePlan.ReadoutStatus.MEASURED,
            completed_at=now - timedelta(days=91),
        )
        other_subscription = self._plan(
            subscription_id=2,
            suffix="other",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )
        OutcomeObservation.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            plan=old,
            run=old.source_action.run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )

        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1, now=now)
        encoded = json.dumps(asdict(memory), default=str, sort_keys=True)

        assert memory.version == 1
        assert {proposal.action_key for proposal in memory.proposals} == {
            active.proposal.stable_action_key,
            recent.proposal.stable_action_key,
        }
        assert other_subscription.proposal.stable_action_key not in encoded
        assert "rationale" not in encoded
        assert "arguments" not in encoded
        assert "result" not in encoded
        assert "must-not-leak" not in encoded
        assert memory.buckets[0].adopted == 1
        assert memory.buckets[0].improved == 1

    @override_settings(PULSE_OUTCOME_MEMORY_MAX_ROWS=1, PULSE_OUTCOME_MEMORY_MAX_BYTES=16_384)
    def test_memory_row_cap_is_applied_after_canonical_encoding(self) -> None:
        self._plan(
            subscription_id=1,
            suffix="first",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )
        self._plan(
            subscription_id=1,
            suffix="second",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )
        self._plan(
            subscription_id=1,
            suffix="third",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )

        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1)

        assert len(memory.proposals) == 1
        assert memory.rows_considered == 2
        assert memory.truncated is True

    @override_settings(PULSE_OUTCOME_MEMORY_MAX_ROWS=50, PULSE_OUTCOME_MEMORY_MAX_BYTES=200)
    def test_memory_byte_cap_is_applied_after_canonical_encoding(self) -> None:
        self._plan(
            subscription_id=1,
            suffix="large",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )

        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1)

        assert memory.proposals == ()
        assert memory.truncated is True
        assert (
            len(json.dumps(asdict(memory), default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")) <= 200
        )

    @override_settings(PULSE_OUTCOME_MEMORY_MAX_ROWS=50, PULSE_OUTCOME_MEMORY_MAX_BYTES=0)
    def test_unusably_small_byte_cap_falls_back_and_bounds_the_complete_dto(self) -> None:
        self._plan(
            subscription_id=1,
            suffix="fallback",
            adoption_status=OutcomePlan.AdoptionStatus.PENDING,
            readout_status=OutcomePlan.ReadoutStatus.WAITING,
        )

        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1)

        assert (
            len(json.dumps(asdict(memory), default=str, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            <= DEFAULT_OUTCOME_MEMORY_MAX_BYTES
        )

    @override_settings(PULSE_OUTCOME_MEMORY_MAX_ROWS=50, PULSE_OUTCOME_MEMORY_MAX_BYTES=78)
    def test_empty_memory_uses_fallback_below_the_79_byte_boundary(self) -> None:
        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1)

        assert (
            len(json.dumps(asdict(memory), default=str, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            <= DEFAULT_OUTCOME_MEMORY_MAX_BYTES
        )

    @override_settings(PULSE_OUTCOME_MEMORY_MAX_ROWS=50, PULSE_OUTCOME_MEMORY_MAX_BYTES=79)
    def test_empty_memory_fits_the_79_byte_boundary(self) -> None:
        memory = build_outcome_memory(team_id=self.team.id, subscription_id=1)

        assert len(json.dumps(asdict(memory), default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")) <= 79

    def test_inconclusive_observations_do_not_reduce_the_measured_improvement_rate(self) -> None:
        measured = self._plan(
            subscription_id=1,
            suffix="measured",
            adoption_status=OutcomePlan.AdoptionStatus.ADOPTED,
            readout_status=OutcomePlan.ReadoutStatus.MEASURED,
        )
        inconclusive = self._plan(
            subscription_id=1,
            suffix="inconclusive",
            adoption_status=OutcomePlan.AdoptionStatus.ADOPTED,
            readout_status=OutcomePlan.ReadoutStatus.INCONCLUSIVE,
        )
        for plan, status, verdict in (
            (measured, OutcomeObservation.Status.MEASURED, OutcomeObservation.Verdict.IMPROVED),
            (inconclusive, OutcomeObservation.Status.INCONCLUSIVE, OutcomeObservation.Verdict.INCONCLUSIVE),
        ):
            OutcomeObservation.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                plan=plan,
                run=plan.source_action.run,
                attempt_number=1,
                status=status,
                verdict=verdict,
            )

        bucket = build_outcome_memory(team_id=self.team.id, subscription_id=1).buckets[0]

        assert bucket.measured == 1
        assert bucket.inconclusive == 1
        assert bucket.improvement_rate == Decimal("1")
