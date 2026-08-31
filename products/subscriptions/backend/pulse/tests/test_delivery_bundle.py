import json
import importlib
import importlib.util
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.exports.backend.facade.api import PersistedAIReportDelivery
from products.exports.backend.models.subscription import SubscriptionDelivery
from products.exports.backend.temporal.subscriptions.ai_subscription.delivery import render_pulse_delivery_appendix
from products.subscriptions.backend.pulse.models import (
    ActionProposal,
    Artifact,
    DeliveryLedger,
    EvidenceSet,
    Opportunity,
    OutcomeObservation,
    OutcomePlan,
    PulseRun,
    RunAction,
)

from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


class TestPulseDeliveryBundle(BaseTest):
    def _module(self):
        if importlib.util.find_spec("products.subscriptions.backend.pulse.delivery_bundle") is None:
            return None
        return importlib.import_module("products.subscriptions.backend.pulse.delivery_bundle")

    def _run(self, *, status: str = PulseRun.Status.COMPLETED) -> tuple[PulseRun, SubscriptionDelivery]:
        subscription = create_subscription(team=self.team, created_by=self.user, prompt="Weekly report")
        delivery = SubscriptionDelivery.objects.create(
            subscription=subscription,
            team=self.team,
            target_type=subscription.target_type,
            target_value=subscription.target_value,
            content_snapshot={"ai_report": "# Base report"},
            idempotency_key=f"pulse-bundle:{uuid4()}",
        )
        run = PulseRun.objects.create(
            team=self.team,
            subscription_id=subscription.id,
            delivery_id=delivery.id,
            status=status,
            config_snapshot={"actor_id": self.user.id, "contexts": []},
            report_snapshot_ref="reports/persisted",
        )
        return run, delivery

    def _action(self, run: PulseRun, *, rank: int, kind: str = RunAction.Kind.DRAFT_PR) -> RunAction:
        opportunity = Opportunity.objects.create(
            team=self.team,
            stable_key=f"opportunity:{rank}:{uuid4()}",
            title=f"Opportunity {rank}",
            summary="Summary",
        )
        proposal = ActionProposal.objects.create(
            team=self.team,
            opportunity=opportunity,
            stable_action_key=f"action:{rank}:{uuid4()}",
            kind=kind,
            normalized_target={},
        )
        return RunAction.objects.create(
            team=self.team,
            run=run,
            opportunity=opportunity,
            proposal=proposal,
            action_key=f"run-action:{rank}:{uuid4()}",
            kind=kind,
            title=f"Action {rank}",
            rationale="Why https://model.example/private",
            expected_impact="Impact",
            rank=rank,
            status=RunAction.Status.COMPLETED,
        )

    def _plan(self, action: RunAction) -> OutcomePlan:
        now = timezone.now()
        return OutcomePlan.objects.create(
            team=self.team,
            subscription_id=action.run.subscription_id,
            proposal=action.proposal,
            source_action=action,
            measurement_spec={"version": 1, "arguments": {"must_not_ship": True}},
            baseline_value=10,
            baseline_from=now - timedelta(days=7),
            baseline_to=now,
        )

    def test_prepare_persists_one_canonical_bounded_safe_bundle(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            first = self._action(run, rank=1)
            first.evidence_set = EvidenceSet.objects.create(
                team=self.team,
                run=run,
                content_hash="a" * 64,
                item_refs=[
                    {
                        "tool_call_id": "evidence:first",
                        "tool_name": "query_insight",
                        "tool_schema_version": "1",
                        "completed_at": "2026-08-29T10:00:00+00:00",
                        "result_hash": "sha256:" + "b" * 64,
                        "raw_result_ref": "must not ship",
                    },
                    {
                        "tool_name": "invalid",
                        "tool_schema_version": "1",
                        "completed_at": "2026-08-29T10:00:00+00:00",
                        "result_hash": "https://model.example/leak",
                    },
                ],
            )
            first.save(update_fields=["evidence_set"])
            Artifact.objects.create(
                team=self.team,
                run=run,
                action=first,
                opportunity_id=first.opportunity_id,
                proposal_id=first.proposal_id,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key=f"artifact:{uuid4()}",
                status=Artifact.Status.VERIFIED,
                external_id="42",
                external_url="https://github.com/posthog/posthog/pull/42",
                metadata={"raw_evidence": "do not ship", "model_url": "https://model.example/leak"},
            )
            for rank in range(2, 5):
                self._action(run, rank=rank)
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base https://model.example/report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id,
                    run_id=run.id,
                    destination="email",
                )

        payload = json.loads(objects[prepared.content_ref])
        assert prepared.logical_key == f"{run.id}:email:bundle:v1"
        assert prepared.provider_idempotency_key == prepared.logical_key
        assert payload["destination_label"] != delivery.target_value
        assert len(payload["destination_label"]) == 16
        assert len(payload["actions"]) == 3
        assert payload["readouts"] == []
        assert payload["actions"][0]["links"]["pull_request"] == "https://github.com/posthog/posthog/pull/42"
        assert payload["actions"][0]["operational_details"]["provenance"] == [
            {
                "tool_name": "query_insight",
                "tool_schema_version": "1",
                "completed_at": "2026-08-29T10:00:00+00:00",
                "result_hash": "sha256:" + "b" * 64,
            }
        ]
        assert delivery.target_value not in json.dumps(payload)
        assert "raw_evidence" not in json.dumps(payload)
        assert "model.example" not in json.dumps(payload)

    def test_bundle_fitting_preserves_contract_values_or_omits_optional_entries_whole(self) -> None:
        bundle = self._module()

        assert bundle is not None
        provenance = [
            {
                "tool_name": "😀" * 255,
                "tool_schema_version": "v" * 128,
                "completed_at": "2026-08-30T10:00:00+00:00",
                "result_hash": f"sha256:{index:064x}",
            }
            for index in range(20)
        ]
        action_ids = [str(uuid4()) for _ in range(3)]
        links = {
            "pull_request": f"https://github.com/posthog/posthog/pull/123?ref={'x' * 12_000}",
            "experiment": f"https://example.com/experiments/{'y' * 12_000}",
        }
        readouts: list[dict[str, object]] = [
            {
                "id": str(uuid4()),
                "plan_id": str(uuid4()),
                "action_id": action_ids[0],
                "recommendation_title": "Readout title",
                "status": "measured",
                "verdict": "improved",
                "baseline_from": "2026-08-01T00:00:00+00:00",
                "baseline_to": "2026-08-08T00:00:00+00:00",
                "links": links.copy(),
            }
        ]
        actions: list[dict[str, object]] = [
            {
                "id": action_id,
                "title": "Action title",
                "why": "Why now",
                "impact": "Expected impact",
                "status": "completed",
                "operational_details": {"status": "verified", "provenance": provenance.copy()},
                "links": links.copy(),
            }
            for action_id in action_ids
        ]
        payload: dict[str, object] = {
            "version": "pulse_delivery_bundle:v1",
            "run_id": str(uuid4()),
            "destination_label": "d" * 16,
            "base_report": "😀" * bundle._MAX_BASE_REPORT_CHARS,
            "readouts": readouts,
            "actions": actions,
            "failures": [{"scope": "action", "code": "action_failed"}],
        }

        encoded = bundle._fit_payload_bytes(payload)

        assert len(encoded) <= 64 * 1024
        assert payload["version"] == "pulse_delivery_bundle:v1"
        assert payload["run_id"]
        assert payload["failures"] == [{"scope": "action", "code": "action_failed"}]
        for action, action_id in zip(actions, action_ids, strict=True):
            assert action["id"] == action_id
            assert action["status"] == "completed"
            operational_details = action["operational_details"]
            assert isinstance(operational_details, dict)
            assert operational_details["status"] == "verified"
            remaining_provenance = operational_details.get("provenance", [])
            assert isinstance(remaining_provenance, list)
            assert remaining_provenance == provenance[: len(remaining_provenance)]
            action_links = action.get("links", {})
            assert isinstance(action_links, dict)
            for link in action_links.values():
                assert link in links.values()
        readout = readouts[0]
        assert readout["status"] == "measured"
        assert readout["verdict"] == "improved"
        assert readout["baseline_from"] == "2026-08-01T00:00:00+00:00"
        assert readout["baseline_to"] == "2026-08-08T00:00:00+00:00"
        readout_links = readout.get("links", {})
        assert isinstance(readout_links, dict)
        for link in readout_links.values():
            assert link in links.values()

    def test_bundle_fitting_shortens_base_report_before_presentation_text(self) -> None:
        bundle = self._module()

        assert bundle is not None
        title = "Presentation title"
        actions = [
            {
                "id": str(uuid4()),
                "title": title,
                "why": "Why now",
                "impact": "Expected impact",
                "status": "completed",
            }
        ]
        payload: dict[str, object] = {
            "version": "pulse_delivery_bundle:v1",
            "run_id": str(uuid4()),
            "destination_label": "d" * 16,
            "base_report": "😀" * bundle._MAX_BASE_REPORT_CHARS,
            "readouts": [],
            "actions": actions,
            "failures": [],
        }

        encoded = bundle._fit_payload_bytes(payload)

        assert len(encoded) <= 64 * 1024
        assert payload["base_report"] != "😀" * bundle._MAX_BASE_REPORT_CHARS
        assert actions[0]["title"] == title

    def test_combined_action_keeps_both_verified_server_owned_artifacts(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            action = self._action(run, rank=1, kind=RunAction.Kind.COMBINED)
            Artifact.objects.create(
                team=self.team,
                run=run,
                action=action,
                opportunity_id=action.opportunity_id,
                proposal_id=action.proposal_id,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key=f"pr:{uuid4()}",
                status=Artifact.Status.VERIFIED,
                external_id="42",
                external_url="https://github.com/posthog/posthog/pull/42",
            )
            Artifact.objects.create(
                team=self.team,
                run=run,
                action=action,
                opportunity_id=action.opportunity_id,
                proposal_id=action.proposal_id,
                kind=Artifact.Kind.EXPERIMENT_DRAFT,
                idempotency_key=f"experiment:{uuid4()}",
                status=Artifact.Status.VERIFIED,
                experiment_id=7,
                external_url="https://model.example/forged",
            )
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )

        payload = json.loads(objects[prepared.content_ref])
        action_payload = payload["actions"][0]
        assert action_payload["links"] == {
            "experiment": f"/project/{self.team.id}/experiments/7",
            "pull_request": "https://github.com/posthog/posthog/pull/42",
        }
        assert len(action_payload["prepared_artifacts"]) == 2
        assert "model.example" not in json.dumps(payload)

    def test_bundle_orders_safe_outcome_readouts_before_recommendations(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            action = self._action(run, rank=1, kind=RunAction.Kind.RECOMMENDATION)
            plan = self._plan(action)
            OutcomeObservation.objects.create(
                team=self.team,
                plan=plan,
                run=run,
                attempt_number=2,
                status=OutcomeObservation.Status.MEASURED,
                observed_value=12,
                absolute_delta=2,
                relative_delta=20,
                verdict=OutcomeObservation.Verdict.IMPROVED,
                confidence="0.8",
            )
            OutcomeObservation.objects.create(
                team=self.team,
                plan=plan,
                run=run,
                attempt_number=1,
                status=OutcomeObservation.Status.FAILED,
                verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
                failure_code="provider_unavailable",
            )
            second_action = self._action(run, rank=2, kind=RunAction.Kind.RECOMMENDATION)
            second_plan = self._plan(second_action)
            OutcomeObservation.objects.create(
                team=self.team,
                plan=second_plan,
                run=run,
                attempt_number=1,
                status=OutcomeObservation.Status.INCONCLUSIVE,
                verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
                failure_code="permissions_lost",
            )
            third_action = self._action(run, rank=3, kind=RunAction.Kind.RECOMMENDATION)
            third_plan = self._plan(third_action)
            OutcomeObservation.objects.create(
                team=self.team,
                plan=third_plan,
                run=run,
                attempt_number=1,
                status=OutcomeObservation.Status.INCONCLUSIVE,
                verdict=OutcomeObservation.Verdict.INCONCLUSIVE,
                failure_code="retry_exhausted",
            )
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )

        encoded = objects[prepared.content_ref]
        payload = json.loads(encoded)
        assert list(payload)[:4] == ["version", "run_id", "destination_label", "base_report"]
        assert payload["readouts"][0]["verdict"] == "improved"
        assert payload["readouts"][1]["failure_code"] == "permissions_lost"
        assert payload["readouts"][2]["failure_code"] == "retry_exhausted"
        assert payload["actions"][0]["adoption_state"] == "pending"
        assert "measurement_spec" not in encoded.decode()

    def test_produced_bundle_renders_readouts_before_actions_with_operational_details(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            outcome_action = self._action(run, rank=1, kind=RunAction.Kind.RECOMMENDATION)
            plan = self._plan(outcome_action)
            plan.measurement_spec = {
                "version": 1,
                "adapter_version": "v1",
                "tool_name": "data-catalog-metric-run",
                "tool_schema_version": "v1",
                "replay_arguments": {
                    "name": "checkout-completions",
                    "date_from": "2026-08-01T00:00:00+00:00",
                    "date_to": "2026-08-08T00:00:00+00:00",
                },
                "selector": {},
                "extraction_kind": "metric_count",
            }
            plan.save(update_fields=["measurement_spec", "updated_at"])
            OutcomeObservation.objects.create(
                team=self.team,
                plan=plan,
                run=run,
                attempt_number=1,
                status=OutcomeObservation.Status.MEASURED,
                observed_value=12,
                absolute_delta=2,
                relative_delta=20,
                verdict=OutcomeObservation.Verdict.IMPROVED,
                confidence="0.8",
            )
            prepared_action = self._action(run, rank=2, kind=RunAction.Kind.DRAFT_PR)
            prepared_action.evidence_set = EvidenceSet.objects.create(
                team=self.team,
                run=run,
                content_hash="a" * 64,
                item_refs=[
                    {
                        "tool_call_id": "evidence:prepared",
                        "tool_name": "query_insight",
                        "tool_schema_version": "v1",
                        "completed_at": "2026-08-29T10:00:00+00:00",
                        "result_hash": "sha256:" + "b" * 64,
                    }
                ],
            )
            prepared_action.save(update_fields=["evidence_set"])
            Artifact.objects.create(
                team=self.team,
                run=run,
                action=prepared_action,
                opportunity_id=prepared_action.opportunity_id,
                proposal_id=prepared_action.proposal_id,
                kind=Artifact.Kind.DRAFT_PR,
                idempotency_key=f"artifact:{uuid4()}",
                status=Artifact.Status.VERIFIED,
                external_id="42",
                external_url="https://github.com/posthog/posthog/pull/42",
            )
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )

        rendered = render_pulse_delivery_appendix(objects[prepared.content_ref])

        assert rendered.markdown.index("## Outcome readouts") < rendered.markdown.index("## Proactive actions")
        assert "Action 1" in rendered.markdown
        assert "- Measurement: Metric checkout-completions (count)" in rendered.markdown
        assert "- Outcome: Improved" in rendered.markdown
        assert "- Baseline: 10.0000000000" in rendered.markdown
        assert "- Observed: 12.0000000000" in rendered.markdown
        assert "- Absolute movement: 2.0000000000" in rendered.markdown
        assert "- Relative movement: 20.0000000000%" in rendered.markdown
        assert "- Confidence: 0.8000" in rendered.markdown
        assert "provider_unavailable" not in rendered.markdown
        assert "### 2. Action 2" in rendered.markdown
        assert "- Adoption: Pending" in rendered.markdown
        assert "- Status: Completed" in rendered.markdown
        assert "- Prepared artifact: Draft pull request: Verified" in rendered.markdown
        assert "- Evidence: `query_insight`" in rendered.markdown
        assert rendered.trusted_links == (("Pull Request", "https://github.com/posthog/posthog/pull/42"),)

    def test_bundle_omits_readout_from_an_unauthorized_source_snapshot(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            source_run, _ = self._run()
            source_run.config_snapshot = {"actor_id": self.user.id, "contexts": [{"insight_id": 999_999}]}
            source_run.save(update_fields=["config_snapshot", "updated_at"])
            source_action = self._action(source_run, rank=1, kind=RunAction.Kind.RECOMMENDATION)
            plan = self._plan(source_action)
            measurement_run, delivery = self._run()
            OutcomeObservation.objects.create(
                team=self.team,
                plan=plan,
                run=measurement_run,
                attempt_number=1,
                status=OutcomeObservation.Status.MEASURED,
                verdict=OutcomeObservation.Verdict.IMPROVED,
            )
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=measurement_run.id, destination="email"
                )

        assert json.loads(objects[prepared.content_ref])["readouts"] == []

    def test_bundle_caps_readouts_after_authorizing_source_snapshots(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            measurement_run, delivery = self._run()
            for rank in range(1, 5):
                source_run, _ = self._run()
                source_run.config_snapshot = {
                    "actor_id": self.user.id if rank == 4 else 999_999,
                    "contexts": [],
                }
                source_run.save(update_fields=["config_snapshot", "updated_at"])
                source_action = self._action(source_run, rank=rank, kind=RunAction.Kind.RECOMMENDATION)
                OutcomeObservation.objects.create(
                    team=self.team,
                    plan=self._plan(source_action),
                    run=measurement_run,
                    attempt_number=1,
                    status=OutcomeObservation.Status.MEASURED,
                    verdict=OutcomeObservation.Verdict.IMPROVED,
                )
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=measurement_run.id, destination="email"
                )

        assert [
            readout["recommendation_title"] for readout in json.loads(objects[prepared.content_ref])["readouts"]
        ] == ["Action 4"]

    def test_bundle_byte_bounds_maximum_unicode_action_text(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            for rank in range(1, 4):
                action = self._action(run, rank=rank, kind=RunAction.Kind.RECOMMENDATION)
                action.title = "😀" * 400
                action.rationale = "😀" * 2_000
                action.expected_impact = "😀" * 1_000
                action.save(update_fields=["title", "rationale", "expected_impact", "updated_at"])
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )

        assert len(objects[prepared.content_ref]) <= 64 * 1024

    def test_retry_recovers_the_exact_bound_bundle_after_a_storage_write_failure(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="email",
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(bundle.object_storage, "write", side_effect=OSError("storage unavailable")),
            ):
                with self.assertRaises(OSError):
                    bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")
                ledger = DeliveryLedger.objects.for_team(self.team.id).get(run_id=run.id, destination="email")
                assert ledger.rendered_content_ref is not None
                assert ledger.rendered_content_hash is not None
                bound_ref = ledger.rendered_content_ref
                bound_hash = ledger.rendered_content_hash

            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                recovered = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )

        assert recovered.content_ref == bound_ref
        assert recovered.content_hash == bound_hash
        assert objects[bound_ref]

    def test_retry_rejects_a_changed_candidate_after_the_ledger_is_bound(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            action = self._action(run, rank=1)
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="email",
                target_value=delivery.target_value,
            )
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(bundle.object_storage, "read_bytes", return_value=None),
                patch.object(bundle.object_storage, "write", side_effect=OSError("storage unavailable")),
            ):
                with self.assertRaises(OSError):
                    bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            action.title = "changed after delivery snapshot"
            action.save(update_fields=["title"])
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(bundle.object_storage, "read_bytes", return_value=None),
                patch.object(bundle.object_storage, "write") as write,
            ):
                with self.assertRaises(bundle.PulseDeliveryBundleConflict):
                    bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            assert write.call_count == 0

    def test_prepare_retries_reuse_the_same_immutable_ledger_and_content(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ) as write,
            ):
                first = bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")
                second = bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            assert first == second
            assert write.call_count == 1
            assert DeliveryLedger.objects.for_team(self.team.id).filter(run_id=run.id, destination="email").count() == 1

    def test_prepare_rejects_a_preexisting_ledger_with_a_different_identity(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, _ = self._run()
            DeliveryLedger.objects.create(
                team=self.team,
                run=run,
                destination="email",
                logical_key="wrong",
                provider_idempotency_key="wrong",
            )

            with self.assertRaises(bundle.PulseDeliveryBundleConflict):
                bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

    def test_begin_rejects_corrupt_content_before_incrementing_the_attempt(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )
                original = objects[prepared.content_ref]
                objects[prepared.content_ref] = b"corrupt"

                with self.assertRaises(bundle.PulseDeliveryBundleConflict):
                    bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

                ledger = DeliveryLedger.objects.for_team(self.team.id).get(id=prepared.ledger_id)
                assert ledger.status == DeliveryLedger.Status.PENDING
                assert ledger.attempt_count == 0

                objects[prepared.content_ref] = original
                attempt = bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            ledger = DeliveryLedger.objects.for_team(self.team.id).get(id=prepared.ledger_id)
            assert attempt.content == original
            assert ledger.status == DeliveryLedger.Status.SENDING
            assert ledger.attempt_count == 1

    def test_ambiguous_provider_outcome_cannot_begin_another_send(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="email",
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")
                bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")
                bundle.finish_pulse_delivery_bundle(
                    team_id=self.team.id,
                    run_id=run.id,
                    destination="email",
                    outcome="delivery_unknown",
                    failure_code="provider_timeout",
                )

                with self.assertRaises(bundle.PulseDeliveryBundleStateError):
                    bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            ledger = DeliveryLedger.objects.for_team(self.team.id).get(run=run, destination="email")
            assert ledger.status == DeliveryLedger.Status.DELIVERY_UNKNOWN
            assert ledger.attempt_count == 1

    def test_slack_retry_after_sending_becomes_unknown_without_a_second_attempt(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="slack",
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="slack")
                bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="slack")

                with self.assertRaises(bundle.PulseDeliveryBundleStateError):
                    bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="slack")

            ledger = DeliveryLedger.objects.for_team(self.team.id).get(run=run, destination="slack")
            assert ledger.status == DeliveryLedger.Status.DELIVERY_UNKNOWN
            assert ledger.failure_code == "provider_outcome_unknown"
            assert ledger.attempt_count == 1

    def test_bundle_preparation_failure_freezes_a_retry_safe_base_report_bundle(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run(status=PulseRun.Status.EXECUTING)
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="email",
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
                patch.object(bundle, "capture_pulse_delivery_prepared") as capture,
            ):
                first = bundle.record_pulse_delivery_bundle_preparation_failure(
                    team_id=self.team.id,
                    run_id=run.id,
                    destination="email",
                    failure_code="pulse_child_failed",
                )
                second = bundle.record_pulse_delivery_bundle_preparation_failure(
                    team_id=self.team.id,
                    run_id=run.id,
                    destination="email",
                    failure_code="pulse_child_failed",
                )

            ledger = DeliveryLedger.objects.for_team(self.team.id).get(run=run, destination="email")
            run.refresh_from_db()
            payload = json.loads(objects[first.content_ref])
            assert second == first
            assert ledger.status == DeliveryLedger.Status.PENDING
            assert ledger.failure_code is None
            assert ledger.rendered_content_hash == first.content_hash
            assert run.status == PulseRun.Status.FAILED
            assert run.failure_code == "pulse_child_failed"
            assert payload["base_report"] == "# Base report"
            assert payload["actions"] == []
            assert payload["failures"] == [{"scope": "run", "code": "pulse_child_failed"}]
            capture.assert_called_once_with(
                team_id=self.team.id,
                run_id=run.id,
                destination="email",
            )

    def test_bundle_fallback_creates_the_deterministic_run_when_start_failed(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            original_run, delivery = self._run()
            subscription_id = original_run.subscription_id
            original_run.delete()
            fallback_run_id = uuid4()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type="email",
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.record_pulse_delivery_bundle_preparation_failure(
                    team_id=self.team.id,
                    run_id=fallback_run_id,
                    destination="email",
                    failure_code="pulse_child_failed",
                    subscription_id=subscription_id,
                    delivery_id=delivery.id,
                    report_snapshot_ref=f"subscription-delivery:{delivery.id}",
                    config_snapshot_ref="dispatch-snapshot",
                )

            run = PulseRun.objects.for_team(self.team.id).get(id=fallback_run_id)
            assert prepared.run_id == fallback_run_id
            assert run.delivery_id == delivery.id
            assert run.status == PulseRun.Status.FAILED
            assert run.failure_code == "pulse_child_failed"
            assert json.loads(objects[prepared.content_ref])["base_report"] == "# Base report"

    def test_prepare_rejects_a_run_that_has_not_reached_a_terminal_state(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, _ = self._run(status=PulseRun.Status.EXECUTING)

            with self.assertRaises(bundle.PulseDeliveryBundleStateError):
                bundle.prepare_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")

            assert DeliveryLedger.objects.for_team(self.team.id).filter(run_id=run.id).count() == 0

    def test_begin_and_finish_resolve_only_the_bound_ledger(self) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                prepared = bundle.prepare_pulse_delivery_bundle(
                    team_id=self.team.id, run_id=run.id, destination="email"
                )
                attempt = bundle.begin_pulse_delivery_bundle_for_ledger(
                    team_id=self.team.id, ledger_id=prepared.ledger_id
                )
                finished = bundle.finish_pulse_delivery_bundle_for_ledger(
                    team_id=self.team.id, ledger_id=prepared.ledger_id, outcome="accepted"
                )

            assert attempt.bundle == prepared
            assert finished == prepared

    @parameterized.expand(
        [
            ("accepted", DeliveryLedger.Status.ACCEPTED, None),
            ("failed", DeliveryLedger.Status.FAILED, "provider_failed"),
            ("delivery_unknown", DeliveryLedger.Status.DELIVERY_UNKNOWN, "provider_timeout"),
        ]
    )
    def test_finish_persists_and_idempotently_replays_an_outcome(
        self,
        _name: str,
        outcome: Literal["accepted", "failed", "delivery_unknown"],
        failure_code: str | None,
    ) -> None:
        bundle = self._module()

        assert bundle is not None
        with team_scope(self.team.id, canonical=True):
            run, delivery = self._run()
            report = PersistedAIReportDelivery(
                delivery_id=delivery.id,
                base_report="# Base report",
                target_type=delivery.target_type,
                target_value=delivery.target_value,
            )
            objects: dict[str, bytes] = {}
            with (
                patch.object(bundle, "get_persisted_ai_report_delivery", return_value=report),
                patch.object(bundle, "capture_pulse_delivery_prepared"),
                patch.object(bundle, "capture_pulse_delivery_finished") as capture_finished,
                patch.object(
                    bundle.object_storage, "read_bytes", side_effect=lambda key, missing_ok=False: objects.get(key)
                ),
                patch.object(
                    bundle.object_storage,
                    "write",
                    side_effect=lambda key, content, extras=None: objects.__setitem__(key, content),
                ),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    prepared = bundle.prepare_pulse_delivery_bundle(
                        team_id=self.team.id, run_id=run.id, destination="email"
                    )
                    bundle.begin_pulse_delivery_bundle(team_id=self.team.id, run_id=run.id, destination="email")
                    first = bundle.finish_pulse_delivery_bundle(
                        team_id=self.team.id,
                        run_id=run.id,
                        destination="email",
                        outcome=outcome,
                        failure_code=failure_code,
                    )
                    second = bundle.finish_pulse_delivery_bundle(
                        team_id=self.team.id,
                        run_id=run.id,
                        destination="email",
                        outcome=outcome,
                        failure_code=failure_code,
                    )

            ledger = DeliveryLedger.objects.for_team(self.team.id).get(id=prepared.ledger_id)
            assert first == second == prepared
            assert ledger.status == outcome
            assert ledger.failure_code == failure_code
            assert (ledger.accepted_at is not None) is (outcome == "accepted")
            capture_finished.assert_called_once_with(
                team_id=self.team.id,
                run_id=run.id,
                destination="email",
                outcome=outcome,
            )
