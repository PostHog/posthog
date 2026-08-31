import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from posthog.models.scoping import team_scope

from products.experiments.backend.facade.contracts import PulseExperimentLifecycleDTO
from products.exports.backend.facade.api import PersistedAIReportDelivery
from products.exports.backend.models.subscription import SubscriptionDelivery
from products.subscriptions.backend.facade.pulse import _import_analysis_evidence
from products.subscriptions.backend.models import (
    ActionProposal,
    Artifact,
    DeliveryLedger,
    Opportunity,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.subscriptions.backend.pulse.contracts import (
    MeasurementCandidate,
    MeasurementEvidence,
    PulseOutcomeReadoutInput,
    PulseOutcomeReadoutPersistenceInput,
)
from products.subscriptions.backend.pulse.delivery_bundle import prepare_pulse_delivery_bundle
from products.subscriptions.backend.pulse.measurements import canonicalize_measurement
from products.subscriptions.backend.pulse.outcomes import (
    claim_due_outcomes,
    create_outcome_plan,
    decide_outcome_plan,
    persist_outcome_readouts,
)
from products.subscriptions.backend.pulse.reaper import _reconcile_outcome_plans
from products.tasks.backend.facade.contracts import CompletedPostHogMCPToolCallDTO, StagedArtifactLifecycleDTO

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


@override_settings(PULSE_PROACTIVE_ENABLED=True, PULSE_OUTCOME_READOUT_ENABLED=True)
class TestPulseOutcomeLoopEndToEnd(BaseTest):
    def _source_action(
        self,
        *,
        subscription_id: int,
        key: str,
        kind: str,
        baseline_from: datetime,
        baseline_to: datetime,
    ) -> tuple[PulseRun, RunAction, OutcomePlan]:
        run = PulseRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            subscription_id=subscription_id,
            delivery_id=uuid4(),
            status=PulseRun.Status.COMPLETED,
            config_snapshot={"actor_id": self.user.id, "contexts": []},
            report_snapshot_ref=f"reports/{key}",
            task_id=uuid4(),
            analysis_task_run_id=uuid4(),
        )
        opportunity = Opportunity.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            stable_key=f"opportunity:{key}",
            title=f"Opportunity {key}",
            summary="A synthetic product opportunity.",
        )
        proposal = ActionProposal.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            opportunity=opportunity,
            stable_action_key=f"proposal:{key}",
            kind=kind,
            normalized_target={"area": key},
        )
        action = RunAction.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"action:{key}",
            kind=kind,
            title=f"Improve {key}",
            rationale="Recent product evidence shows a measurable opportunity.",
            expected_impact="Increase the selected product metric.",
            why_now="The change is recent and the comparison window is complete.",
            confidence=0.8,
            effort="small",
            metric_name="Checkout completion",
            metric_unit=RunAction.MetricUnit.COUNT,
            metric_direction=RunAction.MetricDirection.INCREASE,
            expected_change_type=RunAction.ExpectedChangeType.ABSOLUTE,
            expected_change_lower=Decimal("1"),
            expected_change_upper=Decimal("3"),
            readout_after_days=7,
            rank=1,
            implementation_selected=kind != RunAction.Kind.RECOMMENDATION,
            status=RunAction.Status.COMPLETED,
        )
        baseline_arguments: dict[str, object] = {
            "name": "checkout-completion",
            "date_from": baseline_from.isoformat(),
            "date_to": baseline_to.isoformat(),
            "interval": "day",
        }
        measurement = canonicalize_measurement(
            candidate=MeasurementCandidate(
                run_id=run.id,
                baseline_tool_call_id=f"baseline:{key}",
                metric_name="Checkout completion",
                metric_unit="count",
                direction="increase",
                expected_change_type="absolute",
                expected_change_lower=Decimal("1"),
                expected_change_upper=Decimal("3"),
                readout_after_days=7,
                selector={},
            ),
            evidence=MeasurementEvidence(
                run_id=run.id,
                tool_call_id=f"baseline:{key}",
                tool_name="data-catalog-metric-run",
                tool_schema_version="v1",
                arguments=baseline_arguments,
                result={
                    "status": "approved",
                    "is_drifted": False,
                    "unit": "count",
                    "kind": "EventsNode",
                    "results": [{"count": "10"}],
                },
                completed_at=baseline_to,
            ),
        )
        return run, action, create_outcome_plan(action=action, measurement=measurement)

    def _readout_task_call(
        self, *, tool_call_id: str, observed_from: datetime, observed_to: datetime
    ) -> CompletedPostHogMCPToolCallDTO:
        return CompletedPostHogMCPToolCallDTO(
            tool_call_id=tool_call_id,
            tool_name="data-catalog-metric-run",
            arguments={
                "name": "checkout-completion",
                "date_from": observed_from.isoformat(),
                "date_to": observed_to.isoformat(),
                "interval": "day",
            },
            result={
                "status": "approved",
                "is_drifted": False,
                "unit": "count",
                "kind": "EventsNode",
                "results": [{"count": "14"}],
            },
            completed_at=observed_to,
            is_error=False,
            is_truncated=False,
        )

    def test_closes_the_guided_pm_loop_without_external_side_effects(self) -> None:
        current_time = timezone.now()
        baseline_from = current_time - timedelta(days=14)
        baseline_to = current_time - timedelta(days=7)
        subscription = create_subscription(team=self.team, created_by=self.user, prompt="Weekly product review")

        with team_scope(self.team.id, canonical=True):
            advice_run, _, advice_plan = self._source_action(
                subscription_id=subscription.id,
                key="activation-advice",
                kind=RunAction.Kind.RECOMMENDATION,
                baseline_from=baseline_from,
                baseline_to=baseline_to,
            )
            pr_run, pr_action, pr_plan = self._source_action(
                subscription_id=subscription.id,
                key="checkout-pr",
                kind=RunAction.Kind.DRAFT_PR,
                baseline_from=baseline_from,
                baseline_to=baseline_to,
            )
            experiment_run, _, experiment_plan = self._source_action(
                subscription_id=subscription.id,
                key="onboarding-experiment",
                kind=RunAction.Kind.EXPERIMENT_DRAFT,
                baseline_from=baseline_from,
                baseline_to=baseline_to,
            )
            pr_artifact = Artifact.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                run=pr_run,
                action=pr_action,
                opportunity=pr_action.opportunity,
                proposal=pr_action.proposal,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key="synthetic:checkout-pr",
                external_id="999999",
                external_url="https://github.com/PostHog/posthog/pull/999999",
                task_id=pr_run.task_id,
                execution_task_run_id=uuid4(),
                publication_lease_id=uuid4(),
                status=Artifact.Status.VERIFIED,
            )
            experiment_action = experiment_plan.source_action
            Artifact.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                run=experiment_run,
                action=experiment_action,
                opportunity=experiment_action.opportunity,
                proposal=experiment_action.proposal,
                kind=Artifact.Kind.EXPERIMENT_DRAFT,
                idempotency_key="synthetic:onboarding-experiment",
                experiment_id=999999,
                status=Artifact.Status.VERIFIED,
            )

            decided = decide_outcome_plan(
                team_id=self.team.id,
                plan_id=advice_plan.id,
                decision="adopted",
                actor_id=self.user.id,
                now=current_time,
            )
            with (
                patch(
                    "products.subscriptions.backend.pulse.reaper.tasks_facade.get_staged_artifact_lifecycle",
                    return_value=StagedArtifactLifecycleDTO(
                        state="merged",
                        pr_number=999999,
                        pr_url=pr_artifact.external_url,
                        changed_at=baseline_to,
                    ),
                ),
                patch(
                    "products.subscriptions.backend.pulse.reaper.experiments_facade.get_pulse_experiment_lifecycle",
                    return_value=PulseExperimentLifecycleDTO(
                        experiment_id=999999,
                        state="launched",
                        launched_at=current_time - timedelta(days=1),
                        ended_at=None,
                        result_state="not_ready",
                    ),
                ),
            ):
                assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 2
                assert _reconcile_outcome_plans(now=current_time, batch_size=100) == 1

            advice_plan.refresh_from_db()
            pr_plan.refresh_from_db()
            experiment_plan.refresh_from_db()
            assert decided.adoption_source == OutcomePlan.AdoptionSource.MANUAL
            assert advice_plan.adoption_status == OutcomePlan.AdoptionStatus.ADOPTED
            assert pr_plan.adoption_source == OutcomePlan.AdoptionSource.PULL_REQUEST_MERGED
            assert pr_plan.readout_status == OutcomePlan.ReadoutStatus.DUE
            assert experiment_plan.adoption_source == OutcomePlan.AdoptionSource.EXPERIMENT_LAUNCHED

            delivery = SubscriptionDelivery.objects.create(
                subscription=subscription,
                team=self.team,
                target_type=subscription.target_type,
                target_value=subscription.target_value,
                content_snapshot={"ai_report": "# Weekly product review"},
                idempotency_key=f"pulse-outcome-loop:{uuid4()}",
            )
            measurement_run = PulseRun.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                subscription_id=subscription.id,
                delivery_id=delivery.id,
                config_snapshot={
                    "actor_id": self.user.id,
                    "contexts": [],
                    "flags": {"allow_outcome_readouts": True},
                    "limits": {"max_due_readouts": 3},
                },
                report_snapshot_ref="reports/measurement",
                task_id=uuid4(),
                analysis_task_run_id=uuid4(),
            )
            claims = claim_due_outcomes(
                team_id=self.team.id,
                subscription_id=subscription.id,
                run_id=measurement_run.id,
                now=current_time,
                limit=3,
            )
            assert [claim.plan_id for claim in claims] == [pr_plan.id]
            readout = PulseOutcomeReadoutInput(
                plan_id=pr_plan.id,
                evidence_tool_call_id="readout:checkout-pr",
            )
            with patch(
                "products.subscriptions.backend.facade.pulse.tasks_api.get_completed_posthog_mcp_tool_calls",
                return_value=[
                    self._readout_task_call(
                        tool_call_id="readout:checkout-pr",
                        observed_from=baseline_to,
                        observed_to=current_time,
                    )
                ],
            ):
                _import_analysis_evidence(run=measurement_run, actions=(), readouts=(readout,))
            observations = persist_outcome_readouts(
                PulseOutcomeReadoutPersistenceInput(
                    team_id=self.team.id,
                    run_id=measurement_run.id,
                    now=current_time,
                    readouts=(readout,),
                )
            )
            assert len(observations) == 1
            assert observations[0].verdict == "improved"

            new_opportunity = Opportunity.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                stable_key="opportunity:new-recommendation",
                title="New recommendation",
                summary="A new synthetic recommendation.",
            )
            new_proposal = ActionProposal.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                opportunity=new_opportunity,
                stable_action_key="proposal:new-recommendation",
                kind=ActionProposal.Kind.RECOMMENDATION,
                normalized_target={"area": "retention"},
            )
            new_action = RunAction.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                run=measurement_run,
                opportunity=new_opportunity,
                proposal=new_proposal,
                action_key="action:new-recommendation",
                kind=RunAction.Kind.RECOMMENDATION,
                title="Improve week-one retention",
                rationale="The newest complete cohort is below its prior comparison.",
                expected_impact="Increase week-one retention.",
                why_now="The latest cohort has completed its measurement window.",
                confidence=0.7,
                effort="small",
                metric_name="Week-one retention",
                metric_unit=RunAction.MetricUnit.COUNT,
                metric_direction=RunAction.MetricDirection.INCREASE,
                expected_change_type=RunAction.ExpectedChangeType.ABSOLUTE,
                expected_change_lower=Decimal("1"),
                expected_change_upper=Decimal("3"),
                readout_after_days=7,
                rank=1,
                status=RunAction.Status.PROPOSED,
            )
            create_outcome_plan(
                action=new_action,
                measurement=canonicalize_measurement(
                    candidate=MeasurementCandidate(
                        run_id=measurement_run.id,
                        baseline_tool_call_id="baseline:new-recommendation",
                        metric_name="Week-one retention",
                        metric_unit="count",
                        direction="increase",
                        expected_change_type="absolute",
                        expected_change_lower=Decimal("1"),
                        expected_change_upper=Decimal("3"),
                        readout_after_days=7,
                        selector={},
                    ),
                    evidence=MeasurementEvidence(
                        run_id=measurement_run.id,
                        tool_call_id="baseline:new-recommendation",
                        tool_name="data-catalog-metric-run",
                        tool_schema_version="v1",
                        arguments={
                            "name": "week-one-retention",
                            "date_from": baseline_from.isoformat(),
                            "date_to": baseline_to.isoformat(),
                            "interval": "day",
                        },
                        result={
                            "status": "approved",
                            "is_drifted": False,
                            "unit": "count",
                            "kind": "EventsNode",
                            "results": [{"count": "32"}],
                        },
                        completed_at=baseline_to,
                    ),
                ),
            )
            measurement_run.status = PulseRun.Status.COMPLETED
            measurement_run.finished_at = current_time
            measurement_run.save(update_fields=["status", "finished_at", "updated_at"])

            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Weekly product review",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch(
                    "products.subscriptions.backend.pulse.delivery_bundle.get_persisted_ai_report_delivery",
                    return_value=report,
                ),
                patch(
                    "products.subscriptions.backend.pulse.delivery_bundle.subscription_snapshot_contexts_are_authorized",
                    return_value=True,
                ),
                patch(
                    "products.subscriptions.backend.pulse.delivery_bundle.object_storage.read_bytes",
                    side_effect=lambda key, missing_ok=False: objects.get(key),
                ),
                patch(
                    "products.subscriptions.backend.pulse.delivery_bundle.object_storage.write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ) as write,
            ):
                first = prepare_pulse_delivery_bundle(
                    team_id=self.team.id,
                    run_id=measurement_run.id,
                    destination="email",
                )
                second = prepare_pulse_delivery_bundle(
                    team_id=self.team.id,
                    run_id=measurement_run.id,
                    destination="email",
                )

            payload = json.loads(objects[first.content_ref])
            assert first == second
            assert write.call_count == 1
            assert DeliveryLedger.objects.for_team(self.team.id).filter(run=measurement_run).count() == 1
            assert list(payload).index("readouts") < list(payload).index("actions")
            assert len(payload["readouts"]) == 1
            assert payload["readouts"][0]["recommendation_title"] == pr_action.title
            assert payload["readouts"][0]["verdict"] == "improved"
            assert payload["readouts"][0]["metric_name"] == "Metric checkout-completion"
            assert payload["readouts"][0]["metric_unit"] == "count"
            assert payload["actions"][0]["title"] == new_action.title
            assert "measurement_spec" not in objects[first.content_ref].decode()
            assert advice_run.id != measurement_run.id
