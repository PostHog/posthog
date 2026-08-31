from decimal import Decimal
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError
from posthog.models.team import Team

from products.subscriptions.backend.facade.pulse import (
    PulseValidationError,
    _evidence_provenance,
    create_pulse_run_snapshot,
)
from products.subscriptions.backend.models import PulseRun as CanonicalPulseRun
from products.subscriptions.backend.pulse.contracts import PulseRunSnapshotInput
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

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


class TestPulseModels(BaseTest):
    def test_legacy_model_import_path_reexports_canonical_models(self) -> None:
        assert PulseRun is CanonicalPulseRun

    def test_models_are_team_scoped_uuid_records_with_safe_defaults(self) -> None:
        with self.assertRaises(TeamScopeError):
            ProactiveSubscriptionConfig.objects.count()

        with team_scope(self.team.id, canonical=True):
            subject = PublicResearchSubject.objects.create(
                team=self.team,
                name="Public release notes",
                canonical_domain="example.com",
                query_templates=["site:{canonical_domain} {topic}"],
            )
            config = ProactiveSubscriptionConfig.objects.create(
                team=self.team,
                subscription_id=1,
                public_research_subject=subject,
            )
            grant = RepositoryGrant.objects.create(
                team=self.team,
                config=config,
                authorizer_id=self.user.id,
                automation_owner_id=self.user.id,
                integration_id=1,
                repository_installation_id="123",
                repository="example/repository",
            )
            config.repository_grant = grant
            config.save(update_fields=["repository_grant"])
            run = PulseRun.objects.create(
                team=self.team,
                subscription_id=config.subscription_id,
                delivery_id="019cc802-3939-7f0e-97e3-f538245048f0",
                config_snapshot={},
                report_snapshot_ref="reports/1",
            )
            opportunity = Opportunity.objects.create(
                team=self.team, stable_key="opportunity:1", title="Title", summary="Summary"
            )
            proposal = ActionProposal.objects.create(
                team=self.team,
                opportunity=opportunity,
                stable_action_key="action:1",
                kind=ActionProposal.Kind.DRAFT_PR,
                normalized_target={"repository": "example/repository"},
            )
            evidence_set = EvidenceSet.objects.create(team=self.team, run=run, content_hash="a" * 64, item_refs=[])
            tool_call = EvidenceToolCall.objects.create(
                team=self.team,
                run=run,
                tool_call_id="call-1",
                tool_name="query",
                tool_schema_version="v1",
                normalized_arguments_ref="arguments/1",
                normalized_result_ref="results/1",
            )
            raw_body = EvidenceRawBody.objects.create(
                team=self.team,
                tool_call=tool_call,
                encrypted_arguments='{"query":"safe"}',
                encrypted_result='{"rows":1}',
            )
            action = RunAction.objects.create(
                team=self.team,
                run=run,
                opportunity=opportunity,
                proposal=proposal,
                evidence_set=evidence_set,
                action_key="run-action:1",
                kind=RunAction.Kind.DRAFT_PR,
                title="Title",
                rationale="Rationale",
                expected_impact="Impact",
                rank=1,
            )
            artifact = Artifact.objects.create(
                team=self.team,
                run=run,
                action=action,
                opportunity=opportunity,
                proposal=proposal,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key="proposal:1:draft-pr",
            )
            ledger = DeliveryLedger.objects.create(
                team=self.team,
                run=run,
                destination="email",
                logical_key="run:1:email:bundle:v1",
                provider_idempotency_key="provider:1",
            )

        assert all(
            isinstance(instance.id, UUID)
            for instance in (
                config,
                subject,
                grant,
                run,
                opportunity,
                proposal,
                evidence_set,
                tool_call,
                raw_body,
                action,
                artifact,
                ledger,
            )
        )
        assert config.enabled is False
        assert config.create_draft_pr is False
        assert subject.eligible is True
        assert grant.active is True
        assert run.status == PulseRun.Status.PENDING
        assert opportunity.status == Opportunity.Status.OPEN
        assert proposal.status is None
        assert tool_call.raw_arguments_ref is None
        assert tool_call.raw_result_ref is None
        assert tool_call.raw_expires_at is None
        assert tool_call.purged_at is None
        assert action.status == RunAction.Status.PROPOSED
        assert action.acted_on is False
        assert action.acted_on_at is None
        assert action.acted_on_by_id is None
        assert artifact.status == Artifact.Status.RESERVED
        assert artifact.active_claim is False
        assert ledger.status == DeliveryLedger.Status.PENDING
        assert ledger.attempt_count == 0
        assert ledger.rendered_content_ref is None
        assert ledger.rendered_content_hash is None

    def _create_run(
        self, suffix: str, *, team: Team | None = None, subscription_id: int = 1, status: str = PulseRun.Status.PENDING
    ) -> PulseRun:
        resolved_team = team or self.team
        return PulseRun.objects.create(
            team=resolved_team,
            subscription_id=subscription_id,
            delivery_id=uuid4(),
            status=status,
            config_snapshot={},
            report_snapshot_ref=f"reports/{suffix}",
        )

    def _create_opportunity(self, suffix: str, *, team: Team | None = None) -> Opportunity:
        return Opportunity.objects.create(
            team=team or self.team,
            stable_key=f"opportunity:{suffix}",
            title=f"Title {suffix}",
            summary=f"Summary {suffix}",
        )

    def _create_proposal(
        self, suffix: str, opportunity: Opportunity, *, kind: str = ActionProposal.Kind.DRAFT_PR
    ) -> ActionProposal:
        return ActionProposal.objects.create(
            team=opportunity.team,
            opportunity=opportunity,
            stable_action_key=f"proposal:{suffix}",
            kind=kind,
            normalized_target={},
        )

    def _create_action(
        self,
        suffix: str,
        run: PulseRun,
        opportunity: Opportunity,
        proposal: ActionProposal,
        *,
        kind: str = RunAction.Kind.DRAFT_PR,
        implementation_selected: bool = False,
    ) -> RunAction:
        return RunAction.objects.create(
            team=run.team,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"action:{suffix}",
            kind=kind,
            title=f"Title {suffix}",
            rationale=f"Rationale {suffix}",
            expected_impact=f"Impact {suffix}",
            rank=1,
            implementation_selected=implementation_selected,
        )

    def _create_measurable_recommendation(
        self, suffix: str, *, team: Team | None = None, subscription_id: int = 1
    ) -> RunAction:
        resolved_team = team or self.team
        run = self._create_run(suffix, team=resolved_team, subscription_id=subscription_id)
        opportunity = self._create_opportunity(suffix, team=resolved_team)
        proposal = self._create_proposal(suffix, opportunity, kind=ActionProposal.Kind.RECOMMENDATION)
        return RunAction.objects.create(
            team=resolved_team,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"measurable-action:{suffix}",
            kind=RunAction.Kind.RECOMMENDATION,
            title=f"Title {suffix}",
            rationale=f"Rationale {suffix}",
            expected_impact=f"Impact {suffix}",
            why_now=f"Why now {suffix}",
            metric_name="Checkout completion rate",
            metric_unit="percent",
            metric_direction="increase",
            expected_change_type="relative_percent",
            expected_change_lower=Decimal("2.0"),
            expected_change_upper=Decimal("5.0"),
            readout_after_days=7,
            rank=1,
        )

    def test_outcome_plan_defaults_and_active_proposal_fence(self) -> None:
        with team_scope(self.team.id, canonical=True):
            action = self._create_measurable_recommendation("outcome-plan")
            plan = OutcomePlan.objects.create(
                team=self.team,
                subscription_id=action.run.subscription_id,
                proposal=action.proposal,
                source_action=action,
                measurement_spec={"version": "v1"},
                baseline_value=Decimal("10.0"),
                baseline_from=timezone.now(),
                baseline_to=timezone.now(),
            )

            assert plan.team_id == self.team.id
            assert plan.adoption_status == OutcomePlan.AdoptionStatus.PENDING
            assert plan.readout_status == OutcomePlan.ReadoutStatus.WAITING
            assert plan.attempt_count == 0
            assert plan.claimed_by_run_id is None

            with self.assertRaises(IntegrityError), transaction.atomic():
                OutcomePlan.objects.create(
                    team=self.team,
                    subscription_id=action.run.subscription_id,
                    proposal=action.proposal,
                    source_action=action,
                    measurement_spec={"version": "v1"},
                    baseline_value=Decimal("10.0"),
                    baseline_from=timezone.now(),
                    baseline_to=timezone.now(),
                )

            plan.readout_status = OutcomePlan.ReadoutStatus.MEASURED
            plan.save(update_fields=["readout_status"])
            released_plan = OutcomePlan.objects.create(
                team=self.team,
                subscription_id=action.run.subscription_id,
                proposal=action.proposal,
                source_action=action,
                measurement_spec={"version": "v1"},
                baseline_value=Decimal("10.0"),
                baseline_from=timezone.now(),
                baseline_to=timezone.now(),
            )

        assert released_plan.readout_status == OutcomePlan.ReadoutStatus.WAITING

    def test_outcome_observation_is_immutable_after_creation(self) -> None:
        with team_scope(self.team.id, canonical=True):
            action = self._create_measurable_recommendation("outcome-observation")
            plan = OutcomePlan.objects.create(
                team=self.team,
                subscription_id=action.run.subscription_id,
                proposal=action.proposal,
                source_action=action,
                measurement_spec={"version": "v1"},
                baseline_value=Decimal("10.0"),
                baseline_from=timezone.now(),
                baseline_to=timezone.now(),
            )
            observation = OutcomeObservation.objects.create(
                team=self.team,
                plan=plan,
                run=action.run,
                attempt_number=1,
                status=OutcomeObservation.Status.MEASURED,
                observed_value=Decimal("11.0"),
                observed_from=timezone.now(),
                observed_to=timezone.now(),
                absolute_delta=Decimal("1.0"),
                relative_delta=Decimal("10.0"),
                verdict=OutcomeObservation.Verdict.IMPROVED,
            )

            with self.assertRaises(OutcomeObservation.ImmutableError):
                observation.save()

            with self.assertRaises(OutcomeObservation.ImmutableError):
                observation.delete()

    def test_outcome_records_are_hidden_from_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with team_scope(other_team.id, canonical=True):
            action = self._create_measurable_recommendation("other-outcome", team=other_team)
            plan = OutcomePlan.objects.create(
                team=other_team,
                subscription_id=action.run.subscription_id,
                proposal=action.proposal,
                source_action=action,
                measurement_spec={"version": "v1"},
                baseline_value=Decimal("10.0"),
                baseline_from=timezone.now(),
                baseline_to=timezone.now(),
            )
            observation = OutcomeObservation.objects.create(
                team=other_team,
                plan=plan,
                run=action.run,
                attempt_number=1,
                status=OutcomeObservation.Status.MEASURED,
                verdict=OutcomeObservation.Verdict.IMPROVED,
            )

        with team_scope(self.team.id, canonical=True):
            assert not OutcomePlan.objects.filter(id=plan.id).exists()
            assert not OutcomeObservation.objects.filter(id=observation.id).exists()

    def test_team_scope_hides_other_team_rows_and_for_team_reads_explicitly(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        with team_scope(self.team.id, canonical=True):
            own_opportunity = self._create_opportunity("own")
        with team_scope(other_team.id, canonical=True):
            other_opportunity = self._create_opportunity("other", team=other_team)

        with team_scope(self.team.id, canonical=True):
            assert list(Opportunity.objects.values_list("id", flat=True)) == [own_opportunity.id]
        assert Opportunity.objects.for_team(other_team.id).get().id == other_opportunity.id
        assert Opportunity.objects.for_team(self.team.id).get().id == own_opportunity.id

    def test_config_identity_fence(self) -> None:
        with team_scope(self.team.id, canonical=True):
            ProactiveSubscriptionConfig.objects.create(team=self.team, subscription_id=1)
            with self.assertRaises(IntegrityError), transaction.atomic():
                ProactiveSubscriptionConfig.objects.create(team=self.team, subscription_id=1)

    def test_action_evidence_uses_only_its_evidence_set_references(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._create_run("evidence")
            opportunity = self._create_opportunity("evidence")
            proposal = self._create_proposal("evidence", opportunity)
            first_set = EvidenceSet.objects.create(
                team=self.team,
                run=run,
                content_hash="a" * 64,
                item_refs=[{"tool_call_id": "first"}],
            )
            second_set = EvidenceSet.objects.create(
                team=self.team,
                run=run,
                content_hash="b" * 64,
                item_refs=[{"tool_call_id": "second"}],
            )
            first_action = self._create_action("evidence-first", run, opportunity, proposal)
            first_action.evidence_set = first_set
            first_action.save(update_fields=["evidence_set"])
            second_action = self._create_action("evidence-second", run, opportunity, proposal)
            second_action.evidence_set = second_set
            second_action.rank = 2
            second_action.save(update_fields=["evidence_set", "rank"])
            for tool_call_id in ("first", "second"):
                EvidenceToolCall.objects.create(
                    team=self.team,
                    run=run,
                    tool_call_id=tool_call_id,
                    tool_name=tool_call_id,
                    tool_schema_version="v1",
                    normalized_arguments_ref=f"arguments/{tool_call_id}",
                    normalized_result_ref=f"results/{tool_call_id}",
                )

            first_evidence = _evidence_provenance(team_id=self.team.id, action=first_action)
            second_evidence = _evidence_provenance(team_id=self.team.id, action=second_action)

        assert [item.tool_name for item in first_evidence] == ["first"]
        assert [item.tool_name for item in second_evidence] == ["second"]

    def test_action_evidence_rejects_sets_from_another_run_or_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        with team_scope(self.team.id, canonical=True):
            run = self._create_run("evidence-owner")
            opportunity = self._create_opportunity("evidence-owner")
            proposal = self._create_proposal("evidence-owner", opportunity)
            action = self._create_action("evidence-owner", run, opportunity, proposal)
            other_run = self._create_run("evidence-other-run", subscription_id=2)
            other_run_set = EvidenceSet.objects.create(
                team=self.team,
                run=other_run,
                content_hash="c" * 64,
                item_refs=[{"tool_call_id": "other-run"}],
            )
            EvidenceToolCall.objects.create(
                team=self.team,
                run=other_run,
                tool_call_id="other-run",
                tool_name="other-run",
                tool_schema_version="v1",
                normalized_arguments_ref="arguments/other-run",
                normalized_result_ref="results/other-run",
            )
            action.evidence_set = other_run_set
            action.save(update_fields=["evidence_set"])
            other_run_evidence = _evidence_provenance(team_id=self.team.id, action=action)

        with team_scope(other_team.id, canonical=True):
            foreign_run = self._create_run("evidence-other-team", team=other_team)
            foreign_set = EvidenceSet.objects.create(
                team=other_team,
                run=foreign_run,
                content_hash="d" * 64,
                item_refs=[{"tool_call_id": "other-team"}],
            )

        with team_scope(self.team.id, canonical=True):
            action.evidence_set = foreign_set
            action.save(update_fields=["evidence_set"])
            other_team_evidence = _evidence_provenance(team_id=self.team.id, action=action)

        assert other_run_evidence == []
        assert other_team_evidence == []

    def _snapshot_subscription(self) -> int:
        return create_subscription(
            team=self.team,
            created_by=self.user,
            prompt="Find the next product improvement.",
        ).id

    def _snapshot_config(self, subscription_id: int) -> tuple[ProactiveSubscriptionConfig, RepositoryGrant]:
        config = ProactiveSubscriptionConfig.objects.create(
            team=self.team,
            subscription_id=subscription_id,
            enabled=True,
            repository="posthog/posthog",
            create_draft_pr=True,
        )
        grant = RepositoryGrant.objects.create(
            team=self.team,
            config=config,
            authorizer_id=self.user.id,
            automation_owner_id=self.user.id,
            integration_id=17,
            repository_installation_id="installation-17",
            repository="posthog/posthog",
            capabilities={"draft_pr": True},
        )
        config.repository_grant = grant
        config.save(update_fields=["repository_grant"])
        return config, grant

    def _snapshot_input(self, *, actor_id: int | None = None, integration_id: int | None = 17) -> PulseRunSnapshotInput:
        return PulseRunSnapshotInput(
            delivery_id=uuid4(),
            report_snapshot_ref="reports/proactive",
            original_prompt="Find the next product improvement.",
            contexts=[],
            limits={"max_actions": 1},
            flags={"allow_draft_pr": True},
            actor_id=self.user.id if actor_id is None else actor_id,
            integration_id=integration_id,
            model_version="model-v1",
            normalizer_model_version="normalizer-v1",
        )

    @patch("products.subscriptions.backend.facade.pulse.repository_grant_authorization_is_live", return_value=True)
    def test_snapshot_persists_an_immutable_authorization_grant(self, _repo_authorized: MagicMock) -> None:
        with team_scope(self.team.id, canonical=True):
            subscription_id = self._snapshot_subscription()
            config, grant = self._snapshot_config(subscription_id)
            snapshot_input = self._snapshot_input()
            run = create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription_id,
                snapshot_input=snapshot_input,
            )

            grant.capabilities = {"draft_pr": False}
            grant.active = False
            grant.grant_version = 2
            grant.save(update_fields=["capabilities", "active", "grant_version"])
            config.repository = "other/repository"
            config.save(update_fields=["repository"])

        run.refresh_from_db()
        assert run.config_snapshot["repository"] == "posthog/posthog"
        assert run.config_snapshot["repository_grant_id"] == str(grant.id)
        assert run.config_snapshot["repository_grant_version"] == 1
        assert run.config_snapshot["automation_owner_id"] == self.user.id
        assert run.config_snapshot["actor_id"] == self.user.id
        assert run.config_snapshot["integration_id"] == 17
        assert run.config_snapshot["capabilities"] == {"draft_pr": True}
        assert run.config_snapshot["model_version"] == "model-v1"

    @parameterized.expand(
        [
            ("disabled_config", "disable_config"),
            ("inactive_grant", "deactivate_grant"),
            ("revoked_grant", "revoke_grant"),
            ("grant_from_other_config", "other_config"),
            ("missing_draft_capability", "missing_capability"),
            ("false_draft_capability", "false_capability"),
            ("repository_mismatch", "repository_mismatch"),
        ]
    )
    @patch("products.subscriptions.backend.facade.pulse.repository_grant_authorization_is_live", return_value=True)
    def test_snapshot_rejects_invalid_current_grant(
        self, _name: str, mutation: str, _grant_authorized: MagicMock
    ) -> None:
        with team_scope(self.team.id, canonical=True):
            subscription_id = self._snapshot_subscription()
            config, grant = self._snapshot_config(subscription_id)
            snapshot_input = self._snapshot_input()
            if mutation == "disable_config":
                config.enabled = False
                config.save(update_fields=["enabled"])
            elif mutation == "deactivate_grant":
                grant.active = False
                grant.save(update_fields=["active"])
            elif mutation == "revoke_grant":
                grant.revoked_at = timezone.now()
                grant.save(update_fields=["revoked_at"])
            elif mutation == "other_config":
                other_config = ProactiveSubscriptionConfig.objects.create(
                    team=self.team,
                    subscription_id=subscription_id + 1,
                    enabled=True,
                    repository="posthog/posthog",
                    create_draft_pr=True,
                )
                grant.config = other_config
                grant.save(update_fields=["config"])
            elif mutation == "missing_capability":
                grant.capabilities = {}
                grant.save(update_fields=["capabilities"])
            elif mutation == "false_capability":
                grant.capabilities = {"draft_pr": False}
                grant.save(update_fields=["capabilities"])
            elif mutation == "repository_mismatch":
                config.repository = "other/repository"
                config.save(update_fields=["repository"])
            with self.assertRaises(PulseValidationError):
                create_pulse_run_snapshot(
                    team_id=self.team.id,
                    subscription_id=subscription_id,
                    snapshot_input=snapshot_input,
                )

            assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    @patch("products.subscriptions.backend.facade.pulse.repository_grant_authorization_is_live", return_value=False)
    def test_snapshot_rejects_grant_without_live_repository_authority(self, _grant_authorized: MagicMock) -> None:
        with team_scope(self.team.id, canonical=True):
            subscription_id = self._snapshot_subscription()
            self._snapshot_config(subscription_id)
            snapshot_input = self._snapshot_input()

            with self.assertRaises(PulseValidationError):
                create_pulse_run_snapshot(
                    team_id=self.team.id,
                    subscription_id=subscription_id,
                    snapshot_input=snapshot_input,
                )

            assert not PulseRun.objects.for_team(self.team.id).filter(delivery_id=snapshot_input.delivery_id).exists()

    @patch("products.subscriptions.backend.facade.pulse.repository_grant_authorization_is_live", return_value=True)
    def test_snapshot_uses_grant_integration_instead_of_delivery_integration(
        self, _grant_authorized: MagicMock
    ) -> None:
        with team_scope(self.team.id, canonical=True):
            subscription_id = self._snapshot_subscription()
            self._snapshot_config(subscription_id)
            run = create_pulse_run_snapshot(
                team_id=self.team.id,
                subscription_id=subscription_id,
                snapshot_input=self._snapshot_input(integration_id=18),
            )

        assert run.config_snapshot["integration_id"] == 17

    def test_delivery_and_active_run_fences_release_after_terminal_status(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._create_run("delivery", subscription_id=1)
            with self.assertRaises(IntegrityError), transaction.atomic():
                PulseRun.objects.create(
                    team=self.team,
                    subscription_id=2,
                    delivery_id=run.delivery_id,
                    config_snapshot={},
                    report_snapshot_ref="reports/duplicate-delivery",
                )
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_run("active", subscription_id=1)

            run.status = PulseRun.Status.COMPLETED
            run.save(update_fields=["status"])
            released_run = self._create_run("released", subscription_id=1)

        assert released_run.status == PulseRun.Status.PENDING

    def test_opportunity_and_proposal_identity_fences(self) -> None:
        with team_scope(self.team.id, canonical=True):
            opportunity = self._create_opportunity("identity")
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_opportunity("identity")

            self._create_proposal("identity", opportunity)
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_proposal("identity", opportunity)

    def test_run_action_and_tool_call_identity_fences(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run = self._create_run("action")
            opportunity = self._create_opportunity("action")
            proposal = self._create_proposal("action", opportunity)
            self._create_action("action", run, opportunity, proposal)
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_action("action", run, opportunity, proposal)

            EvidenceToolCall.objects.create(
                team=self.team,
                run=run,
                tool_call_id="call-identity",
                tool_name="query",
                tool_schema_version="v1",
                normalized_arguments_ref="arguments/identity",
                normalized_result_ref="results/identity",
            )
            with self.assertRaises(IntegrityError), transaction.atomic():
                EvidenceToolCall.objects.create(
                    team=self.team,
                    run=run,
                    tool_call_id="call-identity",
                    tool_name="query",
                    tool_schema_version="v1",
                    normalized_arguments_ref="arguments/duplicate",
                    normalized_result_ref="results/duplicate",
                )

    def test_artifact_identity_fences(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run_one = self._create_run("artifact-one", subscription_id=1)
            opportunity = self._create_opportunity("artifact")
            proposal_one = self._create_proposal("artifact-one", opportunity)
            action_one = self._create_action("artifact-one", run_one, opportunity, proposal_one)
            Artifact.objects.create(
                team=self.team,
                run=run_one,
                action=action_one,
                opportunity=opportunity,
                proposal=proposal_one,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key="idempotency-one",
            )

            proposal_two = self._create_proposal("artifact-two", opportunity)
            action_two = self._create_action("artifact-two", run_one, opportunity, proposal_two)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Artifact.objects.create(
                    team=self.team,
                    run=run_one,
                    action=action_two,
                    opportunity=opportunity,
                    proposal=proposal_two,
                    kind=Artifact.Kind.DRAFT_PR,
                    idempotency_key="idempotency-two",
                )

            run_one.status = PulseRun.Status.COMPLETED
            run_one.save(update_fields=["status"])
            run_two = self._create_run("artifact-two", subscription_id=1)
            action_three = self._create_action("artifact-three", run_two, opportunity, proposal_one)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Artifact.objects.create(
                    team=self.team,
                    run=run_two,
                    action=action_three,
                    opportunity=opportunity,
                    proposal=proposal_one,
                    kind=Artifact.Kind.DRAFT_PR,
                    idempotency_key="idempotency-three",
                )

            proposal_three = self._create_proposal("artifact-three", opportunity)
            action_four = self._create_action("artifact-four", run_two, opportunity, proposal_three)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Artifact.objects.create(
                    team=self.team,
                    run=run_two,
                    action=action_four,
                    opportunity=opportunity,
                    proposal=proposal_three,
                    kind=Artifact.Kind.DRAFT_PR,
                    idempotency_key="idempotency-one",
                )

    def test_selected_action_and_active_pr_claim_fences(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run_one = self._create_run("selected", subscription_id=1)
            opportunity = self._create_opportunity("claim")
            selected_proposal = self._create_proposal("selected", opportunity)
            selected_action = self._create_action(
                "selected", run_one, opportunity, selected_proposal, implementation_selected=True
            )
            alternative_proposal = self._create_proposal("alternative", opportunity)
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._create_action(
                    "alternative", run_one, opportunity, alternative_proposal, implementation_selected=True
                )

            Artifact.objects.create(
                team=self.team,
                run=run_one,
                action=selected_action,
                opportunity=opportunity,
                proposal=selected_proposal,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key="claim-active",
                active_claim=True,
                external_state=Artifact.ExternalState.PUBLICATION_UNKNOWN,
                failure_code="refresh_failed",
            )
            run_one.status = PulseRun.Status.COMPLETED
            run_one.save(update_fields=["status"])

            run_two = self._create_run("claim-two", subscription_id=1)
            claim_proposal = self._create_proposal("claim-two", opportunity)
            claim_action = self._create_action("claim-two", run_two, opportunity, claim_proposal)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Artifact.objects.create(
                    team=self.team,
                    run=run_two,
                    action=claim_action,
                    opportunity=opportunity,
                    proposal=claim_proposal,
                    kind=Artifact.Kind.DRAFT_PR,
                    idempotency_key="claim-conflict",
                    active_claim=True,
                )

            inactive_proposal = self._create_proposal("claim-inactive", opportunity)
            inactive_action = self._create_action("claim-inactive", run_two, opportunity, inactive_proposal)
            inactive_artifact = Artifact.objects.create(
                team=self.team,
                run=run_two,
                action=inactive_action,
                opportunity=opportunity,
                proposal=inactive_proposal,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key="claim-inactive",
            )
            run_two.status = PulseRun.Status.COMPLETED
            run_two.save(update_fields=["status"])

            run_three = self._create_run("claim-three", subscription_id=1)
            experiment_proposal = self._create_proposal(
                "claim-experiment", opportunity, kind=ActionProposal.Kind.EXPERIMENT_DRAFT
            )
            experiment_action = self._create_action(
                "claim-experiment", run_three, opportunity, experiment_proposal, kind=RunAction.Kind.EXPERIMENT_DRAFT
            )
            experiment_artifact = Artifact.objects.create(
                team=self.team,
                run=run_three,
                action=experiment_action,
                opportunity=opportunity,
                proposal=experiment_proposal,
                kind=Artifact.Kind.EXPERIMENT_DRAFT,
                idempotency_key="claim-experiment",
                active_claim=True,
            )

        active_artifact = Artifact.objects.for_team(self.team.id).get(idempotency_key="claim-active")
        assert active_artifact.active_claim is True
        assert active_artifact.external_state == Artifact.ExternalState.PUBLICATION_UNKNOWN
        assert inactive_artifact.active_claim is False
        assert experiment_artifact.active_claim is True

    def test_delivery_ledger_identity_fences(self) -> None:
        with team_scope(self.team.id, canonical=True):
            run_one = self._create_run("ledger-one", subscription_id=1)
            DeliveryLedger.objects.create(
                team=self.team,
                run=run_one,
                destination="email",
                logical_key="bundle:one",
                provider_idempotency_key="provider:one",
            )
            with self.assertRaises(IntegrityError), transaction.atomic():
                DeliveryLedger.objects.create(
                    team=self.team,
                    run=run_one,
                    destination="email",
                    logical_key="bundle:two",
                    provider_idempotency_key="provider:two",
                )

            run_one.status = PulseRun.Status.COMPLETED
            run_one.save(update_fields=["status"])
            run_two = self._create_run("ledger-two", subscription_id=1)
            with self.assertRaises(IntegrityError), transaction.atomic():
                DeliveryLedger.objects.create(
                    team=self.team,
                    run=run_two,
                    destination="slack",
                    logical_key="bundle:one",
                    provider_idempotency_key="provider:three",
                )
