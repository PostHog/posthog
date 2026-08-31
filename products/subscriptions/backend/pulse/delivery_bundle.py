"""Immutable, recipient-safe delivery bundles for terminal Pulse runs."""

import re
import json
from dataclasses import field
from hashlib import sha256
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.storage import object_storage

from products.exports.backend.facade.api import (
    get_persisted_ai_report_delivery,
    subscription_snapshot_contexts_are_authorized,
)
from products.subscriptions.backend.pulse.models import (
    Artifact,
    DeliveryLedger,
    OutcomeObservation,
    OutcomePlan,
    PulseRun,
    RunAction,
)
from products.subscriptions.backend.pulse.orchestration import converge_pulse_artifacts_for_terminalization

from .measurements import MeasurementValidationError, measurement_metadata
from .telemetry import capture_pulse_delivery_finished, capture_pulse_delivery_prepared, capture_pulse_run_terminalized

_BUNDLE_VERSION = "pulse_delivery_bundle:v1"
_MAX_ACTIONS = 3
_MAX_READOUTS = 3
_MAX_READOUT_CANDIDATES = 10
_MAX_BUNDLE_BYTES = 64 * 1024
_MAX_BASE_REPORT_CHARS = 24_000
_MAX_ACTION_TITLE_CHARS = 400
_MAX_ACTION_WHY_CHARS = 2_000
_MAX_ACTION_IMPACT_CHARS = 1_000
_MAX_FAILURES = 3
_MAX_FAILURE_CODE_CHARS = 128
_DELIVERY_DESTINATIONS = frozenset({"email", "slack"})
_DELIVERY_OUTCOMES = frozenset({"accepted", "failed", "delivery_unknown"})
_TERMINAL_RUN_STATUSES = frozenset(
    {
        PulseRun.Status.COMPLETED,
        PulseRun.Status.PARTIAL,
        PulseRun.Status.FAILED,
        PulseRun.Status.CANCELLED,
        PulseRun.Status.SKIPPED,
    }
)
_URL_PATTERN = re.compile(r"https?://[^\s<>()\]]+")
_GITHUB_PR_PATH = re.compile(r"^/[^/]+/[^/]+/pull/(\d+)$")


class PulseDeliveryBundleNotFound(ValueError):
    pass


class PulseDeliveryBundleStateError(ValueError):
    pass


class PulseDeliveryBundleConflict(ValueError):
    pass


class PulseDeliveryBundleAlreadyAccepted(ValueError):
    pass


@frozen
class PulseDeliveryBundle:
    ledger_id: UUID
    run_id: UUID
    destination: str
    logical_key: str
    provider_idempotency_key: str
    content_ref: str
    content_hash: str


@frozen
class PulseDeliveryAttempt:
    bundle: PulseDeliveryBundle
    content: bytes = field(repr=False)


@frozen
class _AuthoritativeArtifactLink:
    label: str
    url: str


def prepare_pulse_delivery_bundle(*, team_id: int, run_id: UUID, destination: str) -> PulseDeliveryBundle:
    """Freeze one terminal run into a content-addressed, delivery-safe bundle."""
    _validate_destination(destination)
    prepared = False
    with transaction.atomic():
        run = PulseRun.objects.for_team(team_id).select_for_update().filter(id=run_id).first()
        if run is None:
            raise PulseDeliveryBundleNotFound("Pulse run not found.")
        if run.status not in _TERMINAL_RUN_STATUSES:
            raise PulseDeliveryBundleStateError("Pulse run is not terminal.")

        report = get_persisted_ai_report_delivery(
            team_id=team_id,
            subscription_id=run.subscription_id,
            delivery_id=run.delivery_id,
        )
        if report is None or report.target_type != destination:
            raise PulseDeliveryBundleStateError("Pulse report delivery is unavailable.")

        content = _canonical_bundle_bytes(
            run=run, destination=destination, base_report=report.base_report, target_value=report.target_value
        )
        content_hash = sha256(content).hexdigest()
        content_ref = _content_ref(team_id=team_id, run_id=run.id, content_hash=content_hash)
        logical_key = _logical_key(run_id=run.id, destination=destination)
        ledger = _get_or_create_locked_ledger(
            team_id=team_id, run_id=run.id, destination=destination, logical_key=logical_key
        )
        if ledger.logical_key != logical_key or ledger.provider_idempotency_key != logical_key:
            raise PulseDeliveryBundleConflict("Pulse delivery bundle identity conflicts.")
        if ledger.rendered_content_ref is not None:
            current = _bundle_from_ledger(ledger=ledger, run_id=run_id, destination=destination)
            if current.content_ref != content_ref or current.content_hash != content_hash:
                raise PulseDeliveryBundleConflict("Pulse delivery bundle content conflicts.")
        else:
            ledger.rendered_content_ref = content_ref
            ledger.rendered_content_hash = content_hash
            ledger.save(update_fields=["rendered_content_ref", "rendered_content_hash", "updated_at"])
            current = _bundle_from_ledger(ledger=ledger, run_id=run_id, destination=destination)
            prepared = True

    _write_content_addressed(content_ref=current.content_ref, content=content, content_hash=current.content_hash)
    if prepared:
        capture_pulse_delivery_prepared(team_id=team_id, run_id=run_id, destination=destination)
    return current


def begin_pulse_delivery_bundle(*, team_id: int, run_id: UUID, destination: str) -> PulseDeliveryAttempt:
    """Verify immutable bytes before handing the bundle to a provider."""
    _validate_destination(destination)
    retry_is_ambiguous = False
    bundle: PulseDeliveryBundle | None = None
    with transaction.atomic():
        ledger = _locked_ledger(team_id=team_id, run_id=run_id, destination=destination)
        if ledger.status == DeliveryLedger.Status.ACCEPTED:
            raise PulseDeliveryBundleAlreadyAccepted("Pulse delivery was already accepted.")
        if ledger.status == DeliveryLedger.Status.DELIVERY_UNKNOWN:
            raise PulseDeliveryBundleStateError("Pulse delivery has an ambiguous provider outcome.")
        if ledger.status == DeliveryLedger.Status.SENDING and destination == "slack":
            ledger.status = DeliveryLedger.Status.DELIVERY_UNKNOWN
            ledger.failure_code = "provider_outcome_unknown"
            ledger.save(update_fields=["status", "failure_code", "updated_at"])
            retry_is_ambiguous = True
        else:
            bundle = _bundle_from_ledger(ledger=ledger, run_id=run_id, destination=destination)

    if retry_is_ambiguous:
        raise PulseDeliveryBundleStateError("Pulse delivery has an ambiguous provider outcome.")
    if bundle is None:
        raise PulseDeliveryBundleStateError("Pulse delivery bundle is unavailable.")

    content = object_storage.read_bytes(bundle.content_ref, missing_ok=True)
    if content is None or sha256(content).hexdigest() != bundle.content_hash:
        raise PulseDeliveryBundleConflict("Pulse delivery bundle bytes do not match its hash.")

    retry_is_ambiguous = False
    attempt: PulseDeliveryAttempt | None = None
    with transaction.atomic():
        ledger = _locked_ledger(team_id=team_id, run_id=run_id, destination=destination)
        if ledger.status == DeliveryLedger.Status.ACCEPTED:
            raise PulseDeliveryBundleAlreadyAccepted("Pulse delivery was already accepted.")
        if ledger.status == DeliveryLedger.Status.DELIVERY_UNKNOWN:
            raise PulseDeliveryBundleStateError("Pulse delivery has an ambiguous provider outcome.")
        if ledger.status == DeliveryLedger.Status.SENDING and destination == "slack":
            ledger.status = DeliveryLedger.Status.DELIVERY_UNKNOWN
            ledger.failure_code = "provider_outcome_unknown"
            ledger.save(update_fields=["status", "failure_code", "updated_at"])
            retry_is_ambiguous = True
        else:
            current = _bundle_from_ledger(ledger=ledger, run_id=run_id, destination=destination)
            if current.content_ref != bundle.content_ref or current.content_hash != bundle.content_hash:
                raise PulseDeliveryBundleConflict("Pulse delivery bundle changed before sending.")
            ledger.status = DeliveryLedger.Status.SENDING
            ledger.attempt_count += 1
            ledger.failure_code = None
            ledger.save(update_fields=["status", "attempt_count", "failure_code", "updated_at"])
            attempt = PulseDeliveryAttempt(bundle=current, content=content)

    if retry_is_ambiguous:
        raise PulseDeliveryBundleStateError("Pulse delivery has an ambiguous provider outcome.")
    if attempt is None:
        raise PulseDeliveryBundleStateError("Pulse delivery could not begin.")
    return attempt


def begin_pulse_delivery_bundle_for_ledger(*, team_id: int, ledger_id: UUID) -> PulseDeliveryAttempt:
    """Begin sending through a workflow-held ledger ID without exposing Pulse models."""
    run_id, destination = _ledger_binding(team_id=team_id, ledger_id=ledger_id)
    return begin_pulse_delivery_bundle(team_id=team_id, run_id=run_id, destination=destination)


def finish_pulse_delivery_bundle(
    *,
    team_id: int,
    run_id: UUID,
    destination: str,
    outcome: Literal["accepted", "failed", "delivery_unknown"],
    failure_code: str | None = None,
) -> PulseDeliveryBundle:
    """Persist a provider result without changing the frozen bundle bytes."""
    _validate_destination(destination)
    if outcome not in _DELIVERY_OUTCOMES:
        raise PulseDeliveryBundleStateError("Pulse delivery outcome is unsupported.")
    if outcome == "accepted" and failure_code is not None:
        raise PulseDeliveryBundleConflict("Accepted deliveries cannot have a failure code.")
    bounded_failure_code = _bounded_failure_code(failure_code)
    with transaction.atomic():
        ledger = _locked_ledger(team_id=team_id, run_id=run_id, destination=destination)
        bundle = _bundle_from_ledger(ledger=ledger, run_id=run_id, destination=destination)
        if ledger.status == DeliveryLedger.Status.ACCEPTED:
            if outcome != "accepted":
                raise PulseDeliveryBundleConflict("Accepted deliveries cannot be changed.")
            return bundle
        if ledger.status in {DeliveryLedger.Status.FAILED, DeliveryLedger.Status.DELIVERY_UNKNOWN}:
            if ledger.status != outcome or ledger.failure_code != bounded_failure_code:
                raise PulseDeliveryBundleConflict("Completed delivery result conflicts.")
            return bundle
        if ledger.status != DeliveryLedger.Status.SENDING:
            raise PulseDeliveryBundleStateError("Pulse delivery has not started sending.")
        ledger.status = DeliveryLedger.Status(outcome)
        ledger.failure_code = bounded_failure_code
        ledger.accepted_at = timezone.now() if outcome == "accepted" else None
        ledger.save(update_fields=["status", "failure_code", "accepted_at", "updated_at"])
        transaction.on_commit(
            lambda: capture_pulse_delivery_finished(
                team_id=team_id, run_id=run_id, destination=destination, outcome=outcome
            )
        )
    return bundle


def finish_pulse_delivery_bundle_for_ledger(
    *,
    team_id: int,
    ledger_id: UUID,
    outcome: Literal["accepted", "failed", "delivery_unknown"],
    failure_code: str | None = None,
) -> PulseDeliveryBundle:
    """Record a provider outcome through a workflow-held ledger ID."""
    run_id, destination = _ledger_binding(team_id=team_id, ledger_id=ledger_id)
    return finish_pulse_delivery_bundle(
        team_id=team_id,
        run_id=run_id,
        destination=destination,
        outcome=outcome,
        failure_code=failure_code,
    )


def record_pulse_delivery_bundle_preparation_failure(
    *,
    team_id: int,
    run_id: UUID,
    destination: str,
    failure_code: str = "bundle_prepare_failed",
    subscription_id: int | None = None,
    delivery_id: UUID | None = None,
    report_snapshot_ref: str | None = None,
    config_snapshot_ref: str | None = None,
) -> PulseDeliveryBundle:
    """Freeze a base-report bundle with a local Pulse failure after full preparation fails."""
    _validate_destination(destination)
    bounded_failure_code = _bounded_failure_code(failure_code) or "bundle_prepare_failed"
    prepared = False
    terminalized_status: str | None = None
    with transaction.atomic():
        run = PulseRun.objects.for_team(team_id).select_for_update().filter(id=run_id).first()
        if run is None:
            if delivery_id is not None:
                run = PulseRun.objects.for_team(team_id).select_for_update().filter(delivery_id=delivery_id).first()
            if run is None:
                if subscription_id is None or delivery_id is None or not report_snapshot_ref or not config_snapshot_ref:
                    raise PulseDeliveryBundleNotFound("Pulse run not found.")
                run = PulseRun.objects.for_team(team_id).create(
                    id=run_id,
                    team_id=team_id,
                    subscription_id=subscription_id,
                    delivery_id=delivery_id,
                    status=PulseRun.Status.FAILED,
                    config_snapshot={"version": "v1", "dispatch_snapshot_ref": config_snapshot_ref},
                    report_snapshot_ref=report_snapshot_ref,
                    failure_code=bounded_failure_code,
                    finished_at=timezone.now(),
                )
                terminalized_status = run.status
        if (
            (subscription_id is not None and run.subscription_id != subscription_id)
            or (delivery_id is not None and run.delivery_id != delivery_id)
            or (report_snapshot_ref is not None and run.report_snapshot_ref != report_snapshot_ref)
        ):
            raise PulseDeliveryBundleConflict("Pulse fallback delivery identity conflicts.")
        if run.status not in _TERMINAL_RUN_STATUSES:
            artifacts = list(Artifact.objects.for_team(team_id).select_for_update().filter(run_id=run.id))
            converge_pulse_artifacts_for_terminalization(artifacts=artifacts, failure_code=bounded_failure_code)
            run.status = (
                PulseRun.Status.PARTIAL
                if any(artifact.status == Artifact.Status.VERIFIED for artifact in artifacts)
                else PulseRun.Status.FAILED
            )
            run.failure_code = bounded_failure_code
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "failure_code", "finished_at", "updated_at"])
            terminalized_status = run.status

        report = get_persisted_ai_report_delivery(
            team_id=team_id,
            subscription_id=run.subscription_id,
            delivery_id=run.delivery_id,
        )
        if report is None or report.target_type != destination:
            raise PulseDeliveryBundleStateError("Pulse report delivery is unavailable.")
        content = _fallback_bundle_bytes(
            run=run,
            destination=destination,
            base_report=report.base_report,
            target_value=report.target_value,
            failure_code=bounded_failure_code,
        )
        content_hash = sha256(content).hexdigest()
        content_ref = _content_ref(team_id=team_id, run_id=run.id, content_hash=content_hash)
        logical_key = _logical_key(run_id=run.id, destination=destination)
        ledger = _get_or_create_locked_ledger(
            team_id=team_id,
            run_id=run.id,
            destination=destination,
            logical_key=logical_key,
        )
        if ledger.logical_key != logical_key or ledger.provider_idempotency_key != logical_key:
            raise PulseDeliveryBundleConflict("Pulse delivery bundle identity conflicts.")
        if ledger.status == DeliveryLedger.Status.ACCEPTED:
            raise PulseDeliveryBundleAlreadyAccepted("Pulse delivery was already accepted.")
        if ledger.status in {DeliveryLedger.Status.SENDING, DeliveryLedger.Status.DELIVERY_UNKNOWN}:
            raise PulseDeliveryBundleStateError("Pulse delivery may already have reached the provider.")
        if ledger.rendered_content_ref is not None:
            current = _bundle_from_ledger(ledger=ledger, run_id=run.id, destination=destination)
            if current.content_ref != content_ref or current.content_hash != content_hash:
                raise PulseDeliveryBundleConflict("Pulse delivery bundle content conflicts.")
        else:
            ledger.status = DeliveryLedger.Status.PENDING
            ledger.failure_code = None
            ledger.rendered_content_ref = content_ref
            ledger.rendered_content_hash = content_hash
            ledger.save(
                update_fields=["status", "failure_code", "rendered_content_ref", "rendered_content_hash", "updated_at"]
            )
            current = _bundle_from_ledger(ledger=ledger, run_id=run.id, destination=destination)
            prepared = True
        if terminalized_status is not None:
            transaction.on_commit(
                lambda: capture_pulse_run_terminalized(
                    team_id=team_id,
                    run_id=run.id,
                    status=terminalized_status,
                )
            )

    _write_content_addressed(content_ref=current.content_ref, content=content, content_hash=current.content_hash)
    if prepared:
        capture_pulse_delivery_prepared(team_id=team_id, run_id=run.id, destination=destination)
    return current


def _fallback_bundle_bytes(
    *, run: PulseRun, destination: str, base_report: str, target_value: str, failure_code: str
) -> bytes:
    payload: dict[str, object] = {
        "version": _BUNDLE_VERSION,
        "run_id": str(run.id),
        "destination_label": _destination_label(destination=destination, target_value=target_value),
        "base_report": _safe_text(base_report, _MAX_BASE_REPORT_CHARS),
        "readouts": [],
        "actions": [],
        "failures": [{"scope": "run", "code": failure_code}],
    }
    return _fit_payload_bytes(payload)


def _canonical_bundle_bytes(*, run: PulseRun, destination: str, base_report: str, target_value: str) -> bytes:
    observations = list(
        OutcomeObservation.objects.for_team(run.team_id)
        .select_related("plan", "plan__source_action", "plan__source_action__run")
        .select_for_update(of=("self",))
        .filter(run_id=run.id)
        .exclude(status=OutcomeObservation.Status.FAILED)
        .order_by("created_at", "id")[:_MAX_READOUT_CANDIDATES]
    )
    team = Team.objects.filter(id=run.team_id).first()
    source_actor_ids = {
        source_run.config_snapshot.get("actor_id")
        for source_run in (observation.plan.source_action.run for observation in observations)
        if isinstance(source_run.config_snapshot, dict) and type(source_run.config_snapshot.get("actor_id")) is int
    }
    actors_by_id = User.objects.in_bulk(source_actor_ids)
    observations = [
        observation
        for observation in observations
        if team is not None
        and _source_snapshot_is_authorized(
            team=team,
            source_run=observation.plan.source_action.run,
            actors_by_id=actors_by_id,
        )
    ][:_MAX_READOUTS]
    actions = list(
        RunAction.objects.for_team(run.team_id)
        .select_related("evidence_set")
        .select_for_update(of=("self",))
        .filter(run_id=run.id)
        .order_by("rank", "id")[:_MAX_ACTIONS]
    )
    action_ids = {action.id for action in actions}
    action_ids.update(observation.plan.source_action_id for observation in observations)
    plans_by_action = {
        plan.source_action_id: plan
        for plan in OutcomePlan.objects.for_team(run.team_id).filter(source_action_id__in=action_ids)
    }
    artifacts_by_action: dict[UUID, list[Artifact]] = {}
    for artifact in (
        Artifact.objects.for_team(run.team_id)
        .select_for_update()
        .filter(action_id__in=action_ids)
        .order_by("kind", "id")
    ):
        artifacts_by_action.setdefault(artifact.action_id, []).append(artifact)
    action_payloads = [
        _action_payload(
            action=action,
            plan=plans_by_action.get(action.id),
            artifacts=artifacts_by_action.get(action.id, []),
        )
        for action in actions
    ]
    payload: dict[str, object] = {
        "version": _BUNDLE_VERSION,
        "run_id": str(run.id),
        "destination_label": _destination_label(destination=destination, target_value=target_value),
        "base_report": _safe_text(base_report, _MAX_BASE_REPORT_CHARS),
        "readouts": [
            _readout_payload(
                observation=observation,
                artifacts=artifacts_by_action.get(observation.plan.source_action_id, []),
            )
            for observation in observations
        ],
        "actions": action_payloads,
        "failures": _failures(run=run, actions=actions, artifacts_by_action=artifacts_by_action),
    }
    return _fit_payload_bytes(payload)


def _source_snapshot_is_authorized(*, team: Team, source_run: PulseRun, actors_by_id: dict[int, User]) -> bool:
    snapshot = source_run.config_snapshot
    if not isinstance(snapshot, dict):
        return False
    actor_id = snapshot.get("actor_id")
    if type(actor_id) is not int:
        return False
    actor = actors_by_id.get(actor_id)
    return (
        actor is not None
        and actor.is_active
        and subscription_snapshot_contexts_are_authorized(
            team=team,
            user=actor,
            subscription_id=source_run.subscription_id,
            contexts=snapshot.get("contexts"),
        )
    )


def _action_payload(*, action: RunAction, plan: OutcomePlan | None, artifacts: list[Artifact]) -> dict[str, object]:
    valid_artifacts = [
        artifact for artifact in artifacts if _artifact_belongs_to_action(artifact=artifact, action=action)
    ]
    operational_details: dict[str, object] = {"status": action.status}
    links: dict[str, str] = {}
    artifact_results: list[dict[str, object]] = []
    for artifact in valid_artifacts:
        result: dict[str, object] = {"kind": artifact.kind, "status": artifact.status}
        if artifact.failure_code:
            result["failure_code"] = _bounded_failure_code(artifact.failure_code)
        if artifact.task_id is not None:
            result["task_id"] = str(artifact.task_id)
        artifact_results.append(result)
        link = _authoritative_artifact_link(artifact)
        if link is not None:
            links[link.label] = link.url
    provenance = _safe_provenance(action.evidence_set.item_refs) if action.evidence_set is not None else []
    if provenance:
        operational_details["provenance"] = provenance
    payload: dict[str, object] = {
        "rank": action.rank,
        "kind": action.kind,
        "title": _safe_text(action.title, _MAX_ACTION_TITLE_CHARS),
        "why": _safe_text(action.rationale, _MAX_ACTION_WHY_CHARS),
        "impact": _safe_text(action.expected_impact, _MAX_ACTION_IMPACT_CHARS),
        "adoption_state": plan.adoption_status if plan is not None else "pending",
        "prepared_artifacts": artifact_results,
        "operational_details": operational_details,
        "links": links,
    }
    return payload


def _readout_payload(*, observation: OutcomeObservation, artifacts: list[Artifact]) -> dict[str, object]:
    plan = observation.plan
    action = plan.source_action
    try:
        metric_name, metric_unit = measurement_metadata(specification=plan.measurement_spec)
    except MeasurementValidationError:
        metric_name, metric_unit = "Count", "count"
    links: dict[str, str] = {}
    prepared_artifacts: list[dict[str, object]] = []
    for artifact in artifacts:
        if not _artifact_belongs_to_action(artifact=artifact, action=action):
            continue
        artifact_payload: dict[str, object] = {"kind": artifact.kind, "status": artifact.status}
        if artifact.failure_code:
            artifact_payload["failure_code"] = _bounded_failure_code(artifact.failure_code)
        prepared_artifacts.append(artifact_payload)
        link = _authoritative_artifact_link(artifact)
        if link is not None:
            links[link.label] = link.url
    return {
        "recommendation_title": _safe_text(action.title, _MAX_ACTION_TITLE_CHARS),
        "metric_name": metric_name,
        "metric_unit": metric_unit,
        "baseline_value": str(plan.baseline_value),
        "baseline_from": plan.baseline_from.isoformat(),
        "baseline_to": plan.baseline_to.isoformat(),
        "observed_value": str(observation.observed_value) if observation.observed_value is not None else None,
        "observed_from": observation.observed_from.isoformat() if observation.observed_from is not None else None,
        "observed_to": observation.observed_to.isoformat() if observation.observed_to is not None else None,
        "absolute_delta": str(observation.absolute_delta) if observation.absolute_delta is not None else None,
        "relative_delta": str(observation.relative_delta) if observation.relative_delta is not None else None,
        "status": observation.status,
        "verdict": observation.verdict,
        "confidence": str(observation.confidence) if observation.confidence is not None else None,
        "failure_code": _bounded_failure_code(observation.failure_code),
        "prepared_artifacts": prepared_artifacts,
        "links": links,
    }


def _safe_provenance(raw_refs: object) -> list[dict[str, str]]:
    if not isinstance(raw_refs, list):
        return []
    provenance: list[dict[str, str]] = []
    for item in raw_refs[:20]:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool_name")
        schema_version = item.get("tool_schema_version")
        completed_at = item.get("completed_at")
        result_hash = item.get("result_hash")
        if (
            not isinstance(tool_name, str)
            or not tool_name
            or len(tool_name) > 255
            or not isinstance(schema_version, str)
            or not schema_version
            or len(schema_version) > 128
            or not isinstance(completed_at, str)
            or not completed_at
            or len(completed_at) > 64
            or not isinstance(result_hash, str)
            or not result_hash.startswith("sha256:")
            or len(result_hash) != 71
            or any(character not in "0123456789abcdef" for character in result_hash[7:])
        ):
            continue
        provenance.append(
            {
                "tool_name": tool_name,
                "tool_schema_version": schema_version,
                "completed_at": completed_at,
                "result_hash": result_hash,
            }
        )
    return provenance


def _failures(
    *, run: PulseRun, actions: list[RunAction], artifacts_by_action: dict[UUID, list[Artifact]]
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    if run.failure_code:
        failures.append({"scope": "run", "code": _bounded_failure_code(run.failure_code)})
    for action in actions:
        if len(failures) >= _MAX_FAILURES:
            break
        if action.status == RunAction.Status.FAILED:
            failures.append({"scope": "action", "rank": action.rank, "code": "action_failed"})
        else:
            for artifact in artifacts_by_action.get(action.id, []):
                if artifact.failure_code and len(failures) < _MAX_FAILURES:
                    failures.append(
                        {"scope": "artifact", "rank": action.rank, "code": _bounded_failure_code(artifact.failure_code)}
                    )
    return failures[:_MAX_FAILURES]


def _encode_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _fit_payload_bytes(payload: dict[str, object]) -> bytes:
    encoded = _encode_payload(payload)
    if len(encoded) <= _MAX_BUNDLE_BYTES:
        return encoded

    _shorten_presentation_field(payload, payload, "base_report")
    for action in _payload_items(payload, "actions"):
        for field_name in ("title", "why", "impact"):
            if len(_encode_payload(payload)) <= _MAX_BUNDLE_BYTES:
                return _encode_payload(payload)
            _shorten_presentation_field(payload, action, field_name)
    for readout in _payload_items(payload, "readouts"):
        if len(_encode_payload(payload)) <= _MAX_BUNDLE_BYTES:
            return _encode_payload(payload)
        _shorten_presentation_field(payload, readout, "recommendation_title")

    for action in reversed(_payload_items(payload, "actions")):
        operational_details = action.get("operational_details")
        if not isinstance(operational_details, dict):
            continue
        provenance = operational_details.get("provenance")
        if not isinstance(provenance, list):
            continue
        while provenance and len(_encode_payload(payload)) > _MAX_BUNDLE_BYTES:
            provenance.pop()
        if not provenance:
            operational_details.pop("provenance", None)
        if len(_encode_payload(payload)) <= _MAX_BUNDLE_BYTES:
            return _encode_payload(payload)

    for item in [*_payload_items(payload, "readouts"), *_payload_items(payload, "actions")]:
        _omit_optional_mapping_entries(payload, item, "links")
        _omit_optional_list_entries(payload, item, "prepared_artifacts")
        if len(_encode_payload(payload)) <= _MAX_BUNDLE_BYTES:
            return _encode_payload(payload)

    encoded = _encode_payload(payload)
    if len(encoded) > _MAX_BUNDLE_BYTES:
        raise PulseDeliveryBundleStateError("Pulse delivery bundle exceeds its size limit.")
    return encoded


def _shorten_presentation_field(payload: dict[str, object], container: dict[str, object], field_name: str) -> None:
    value = container.get(field_name)
    while isinstance(value, str) and value and len(_encode_payload(payload)) > _MAX_BUNDLE_BYTES:
        shortened = value[: len(value) // 2]
        container[field_name] = shortened
        value = shortened


def _payload_items(payload: dict[str, object], field_name: str) -> list[dict[str, object]]:
    value = payload.get(field_name)
    if not isinstance(value, list):
        return []
    return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]


def _omit_optional_mapping_entries(payload: dict[str, object], item: dict[str, object], field_name: str) -> None:
    value = item.get(field_name)
    while isinstance(value, dict) and value and len(_encode_payload(payload)) > _MAX_BUNDLE_BYTES:
        value.pop(next(reversed(value)))
    if isinstance(value, dict) and not value:
        item.pop(field_name, None)


def _omit_optional_list_entries(payload: dict[str, object], item: dict[str, object], field_name: str) -> None:
    value = item.get(field_name)
    while isinstance(value, list) and value and len(_encode_payload(payload)) > _MAX_BUNDLE_BYTES:
        value.pop()
    if isinstance(value, list) and not value:
        item.pop(field_name, None)


def _safe_text(value: str, limit: int) -> str:
    return _URL_PATTERN.sub("[link omitted]", value.replace("\x00", "").strip())[:limit]


def _bounded_failure_code(value: str | None) -> str | None:
    return value[:_MAX_FAILURE_CODE_CHARS] if value else None


def _destination_label(*, destination: str, target_value: str) -> str:
    return sha256(f"{destination}:{target_value}".encode()).hexdigest()[:16]


def _logical_key(*, run_id: UUID, destination: str) -> str:
    return f"{run_id}:{destination}:bundle:v1"


def _content_ref(*, team_id: int, run_id: UUID, content_hash: str) -> str:
    return f"subscriptions/pulse/delivery-bundles/v1/{team_id}/{run_id}/{content_hash}.json"


def _write_content_addressed(*, content_ref: str, content: bytes, content_hash: str) -> None:
    current = object_storage.read_bytes(content_ref, missing_ok=True)
    if current is not None:
        if sha256(current).hexdigest() != content_hash:
            raise PulseDeliveryBundleConflict("Pulse delivery bundle storage content conflicts.")
        return
    object_storage.write(content_ref, content, extras={"ContentType": "application/json"})


def _get_or_create_locked_ledger(*, team_id: int, run_id: UUID, destination: str, logical_key: str) -> DeliveryLedger:
    ledger = (
        DeliveryLedger.objects.for_team(team_id)
        .select_for_update()
        .filter(run_id=run_id, destination=destination)
        .first()
    )
    if ledger is not None:
        return ledger
    try:
        with transaction.atomic():
            return DeliveryLedger.objects.for_team(team_id).create(
                team_id=team_id,
                run_id=run_id,
                destination=destination,
                logical_key=logical_key,
                provider_idempotency_key=logical_key,
            )
    except IntegrityError:
        ledger = (
            DeliveryLedger.objects.for_team(team_id)
            .select_for_update()
            .filter(run_id=run_id, destination=destination)
            .first()
        )
        if ledger is not None:
            return ledger
        raise


def _artifact_belongs_to_action(*, artifact: Artifact, action: RunAction) -> bool:
    if (
        artifact.team_id != action.team_id
        or artifact.run_id != action.run_id
        or artifact.opportunity_id != action.opportunity_id
        or artifact.proposal_id != action.proposal_id
    ):
        return False
    return action.kind == RunAction.Kind.COMBINED or artifact.kind == action.kind


def _authoritative_artifact_link(artifact: Artifact) -> _AuthoritativeArtifactLink | None:
    if artifact.status != Artifact.Status.VERIFIED:
        return None
    if artifact.kind == Artifact.Kind.EXPERIMENT_DRAFT and artifact.experiment_id is not None:
        return _AuthoritativeArtifactLink(
            label="experiment",
            url=f"/project/{artifact.team_id}/experiments/{artifact.experiment_id}",
        )
    if artifact.kind != Artifact.Kind.DRAFT_PR or not artifact.external_url or not artifact.external_id:
        return None
    parsed = urlsplit(artifact.external_url)
    match = _GITHUB_PR_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or match is None
        or match.group(1) != artifact.external_id
    ):
        return None
    return _AuthoritativeArtifactLink(label="pull_request", url=artifact.external_url)


def _locked_ledger(*, team_id: int, run_id: UUID, destination: str) -> DeliveryLedger:
    ledger = (
        DeliveryLedger.objects.for_team(team_id)
        .select_for_update()
        .filter(run_id=run_id, destination=destination)
        .first()
    )
    if ledger is None:
        raise PulseDeliveryBundleNotFound("Pulse delivery bundle not found.")
    return ledger


def _ledger_binding(*, team_id: int, ledger_id: UUID) -> tuple[UUID, str]:
    binding = DeliveryLedger.objects.for_team(team_id).filter(id=ledger_id).values_list("run_id", "destination").first()
    if binding is None:
        raise PulseDeliveryBundleNotFound("Pulse delivery bundle not found.")
    run_id, destination = binding
    if not isinstance(run_id, UUID) or not isinstance(destination, str):
        raise PulseDeliveryBundleConflict("Pulse delivery bundle is invalid.")
    return run_id, destination


def _bundle_from_ledger(*, ledger: DeliveryLedger, run_id: UUID, destination: str) -> PulseDeliveryBundle:
    logical_key = _logical_key(run_id=run_id, destination=destination)
    if (
        ledger.logical_key != logical_key
        or ledger.provider_idempotency_key != logical_key
        or not ledger.rendered_content_ref
        or not ledger.rendered_content_hash
        or ledger.rendered_content_ref
        != _content_ref(team_id=ledger.team_id, run_id=run_id, content_hash=ledger.rendered_content_hash)
    ):
        raise PulseDeliveryBundleConflict("Pulse delivery bundle is invalid.")
    return PulseDeliveryBundle(
        ledger_id=ledger.id,
        run_id=run_id,
        destination=destination,
        logical_key=logical_key,
        provider_idempotency_key=logical_key,
        content_ref=ledger.rendered_content_ref,
        content_hash=ledger.rendered_content_hash,
    )


def _validate_destination(destination: str) -> None:
    if destination not in _DELIVERY_DESTINATIONS:
        raise PulseDeliveryBundleStateError("Pulse delivery destination is unsupported.")
