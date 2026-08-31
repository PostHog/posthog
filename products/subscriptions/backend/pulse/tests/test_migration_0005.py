from typing import Any
from uuid import uuid4

from posthog.test.base import NonAtomicTestMigrations

from django.db import DatabaseError, transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.subscriptions.backend.models import (
    ImmutableOutcomeObservationQuerySet,
    OutcomeObservation,
    OutcomePlan,
    RunAction,
)


class OutcomeLoopMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0003_pulserun_orchestration_state"
    migrate_to = "0005_outcome_observation_immutability"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "subscriptions"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        PulseRun = apps.get_model("subscriptions", "PulseRun")
        Opportunity = apps.get_model("subscriptions", "Opportunity")
        ActionProposal = apps.get_model("subscriptions", "ActionProposal")
        RunAction = apps.get_model("subscriptions", "RunAction")

        organization = Organization.objects.create(name="Outcome migration organization")
        project = Project.objects.create(id=999994, organization=organization, name="Outcome migration project")
        team = Team.objects.create(organization=organization, project=project, name="Outcome migration team")

        def create_action(suffix: str, *, acted_on_by_id: int | None) -> Any:
            run = PulseRun.all_teams.create(
                team=team,
                subscription_id=1 if acted_on_by_id is not None else 2,
                delivery_id=uuid4(),
                config_snapshot={},
                report_snapshot_ref=f"reports/{suffix}",
            )
            opportunity = Opportunity.all_teams.create(
                team=team,
                stable_key=f"opportunity:{suffix}",
                title=f"Title {suffix}",
                summary=f"Summary {suffix}",
            )
            proposal = ActionProposal.all_teams.create(
                team=team,
                opportunity=opportunity,
                stable_action_key=f"proposal:{suffix}",
                kind="recommendation",
                normalized_target={},
            )
            return RunAction.all_teams.create(
                team=team,
                run=run,
                opportunity=opportunity,
                proposal=proposal,
                action_key=f"action:{suffix}",
                kind="recommendation",
                title=f"Title {suffix}",
                rationale=f"Rationale {suffix}",
                expected_impact=f"Impact {suffix}",
                rank=1,
                acted_on=True,
                acted_on_at=timezone.now(),
                acted_on_by_id=acted_on_by_id,
            )

        manual_action = create_action("manual", acted_on_by_id=123)
        automatic_action = create_action("automatic", acted_on_by_id=None)
        self.manual_action_id = manual_action.id
        self.manual_acted_on_at = manual_action.acted_on_at
        self.automatic_action_id = automatic_action.id
        self.automatic_acted_on_at = automatic_action.acted_on_at
        self.team_id = team.id

    def test_legacy_acted_on_rows_remain_history_without_synthetic_plans(self) -> None:
        assert self.apps is not None
        OutcomePlan = self.apps.get_model("subscriptions", "OutcomePlan")
        RunAction = self.apps.get_model("subscriptions", "RunAction")

        manual_action = RunAction.all_teams.get(id=self.manual_action_id)
        automatic_action = RunAction.all_teams.get(id=self.automatic_action_id)

        assert manual_action.acted_on is True
        assert manual_action.acted_on_by_id == 123
        assert manual_action.acted_on_at == self.manual_acted_on_at
        assert automatic_action.acted_on is True
        assert automatic_action.acted_on_by_id is None
        assert automatic_action.acted_on_at == self.automatic_acted_on_at
        for action in (manual_action, automatic_action):
            for field in (
                "why_now",
                "metric_name",
                "metric_unit",
                "metric_direction",
                "expected_change_type",
                "expected_change_lower",
                "expected_change_upper",
                "readout_after_days",
            ):
                assert getattr(action, field) is None
        assert OutcomePlan.all_teams.count() == 0

    def test_observation_trigger_rejects_scoped_bulk_update_and_all_team_bulk_delete(self) -> None:
        source_action = RunAction.all_teams.get(id=self.manual_action_id)
        plan = OutcomePlan.all_teams.create(
            team_id=self.team_id,
            subscription_id=source_action.run.subscription_id,
            proposal_id=source_action.proposal_id,
            source_action_id=source_action.id,
            measurement_spec={"version": "v1"},
            baseline_value="10.0",
            baseline_from=timezone.now(),
            baseline_to=timezone.now(),
        )
        observation = OutcomeObservation.all_teams.create(
            team_id=self.team_id,
            plan=plan,
            run=source_action.run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )

        with (
            team_scope(self.team_id, canonical=True),
            self.assertRaises(OutcomeObservation.ImmutableError),
            transaction.atomic(),
        ):
            OutcomeObservation.objects.filter(id=observation.id).update(status=OutcomeObservation.Status.FAILED)

        with (
            team_scope(self.team_id, canonical=True),
            self.assertRaises(OutcomeObservation.ImmutableError),
            transaction.atomic(),
        ):
            OutcomeObservation.objects.filter(id=observation.id).delete()

        with self.assertRaises(OutcomeObservation.ImmutableError), transaction.atomic():
            OutcomeObservation.all_teams.filter(id=observation.id).update(status=OutcomeObservation.Status.FAILED)

        with self.assertRaises(OutcomeObservation.ImmutableError), transaction.atomic():
            OutcomeObservation.all_teams.filter(id=observation.id).delete()

        with (
            team_scope(self.team_id, canonical=True),
            self.assertRaises(OutcomeObservation.ImmutableError),
            transaction.atomic(),
        ):
            scoped_observations = OutcomeObservation.objects.filter(id=observation.id)
            assert isinstance(scoped_observations, ImmutableOutcomeObservationQuerySet)
            scoped_observations.unscoped().update(status=OutcomeObservation.Status.FAILED)

        with (
            team_scope(self.team_id, canonical=True),
            self.assertRaises(OutcomeObservation.ImmutableError),
            transaction.atomic(),
        ):
            scoped_observations = OutcomeObservation.objects.filter(id=observation.id)
            assert isinstance(scoped_observations, ImmutableOutcomeObservationQuerySet)
            scoped_observations.unscoped().delete()

        with self.assertRaises(OutcomeObservation.ImmutableError), transaction.atomic():
            all_team_observations = OutcomeObservation.all_teams.filter(id=observation.id)
            assert isinstance(all_team_observations, ImmutableOutcomeObservationQuerySet)
            all_team_observations.unscoped().update(status=OutcomeObservation.Status.FAILED)

        with self.assertRaises(OutcomeObservation.ImmutableError), transaction.atomic():
            all_team_observations = OutcomeObservation.all_teams.filter(id=observation.id)
            assert isinstance(all_team_observations, ImmutableOutcomeObservationQuerySet)
            all_team_observations.unscoped().delete()

    def test_team_deletion_cascades_to_outcome_observations(self) -> None:
        source_action = RunAction.all_teams.get(id=self.manual_action_id)
        plan = OutcomePlan.all_teams.create(
            team_id=self.team_id,
            subscription_id=source_action.run.subscription_id,
            proposal_id=source_action.proposal_id,
            source_action_id=source_action.id,
            measurement_spec={"version": "v1"},
            baseline_value="10.0",
            baseline_from=timezone.now(),
            baseline_to=timezone.now(),
        )
        observation = OutcomeObservation.all_teams.create(
            team_id=self.team_id,
            plan=plan,
            run=source_action.run,
            attempt_number=1,
            status=OutcomeObservation.Status.MEASURED,
            verdict=OutcomeObservation.Verdict.IMPROVED,
        )

        Team.objects.get(id=self.team_id).delete()

        assert not OutcomeObservation.all_teams.filter(id=observation.id).exists()

    def test_readout_delay_constraint_rejects_unsupported_value(self) -> None:
        with self.assertRaises(DatabaseError), transaction.atomic():
            RunAction.all_teams.filter(id=self.manual_action_id).update(readout_after_days=1)
