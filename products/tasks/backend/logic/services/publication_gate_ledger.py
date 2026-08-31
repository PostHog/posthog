"""Durable, server-owned records for protected-base publication gates."""

from __future__ import annotations

import hashlib
from datetime import datetime

from django.db import IntegrityError
from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen
from posthog.storage import object_storage

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.logic.services.publication_gates import (
    PublicationGateDefinition,
    ResolvedPublicationGatePolicy,
)
from products.tasks.backend.logic.services.staged_task_runs import with_validated_staged_draft_publication
from products.tasks.backend.models import (
    TaskDraftPublication,
    TaskPublicationGateLedger,
    TaskPublicationGatePolicy,
    TaskPublicationLease,
)

_MAX_GATE_OUTPUT_BYTES = 64 * 1024


class PublicationGateError(RuntimeError):
    """A server-required publication gate did not have an authoritative success."""


@frozen
class PublicationGateExecution:
    gate_key: str
    label: str
    argv: tuple[str, ...]


@frozen
class PublicationGateStatus:
    overall_status: str
    completed_at: datetime | None
    gates: tuple[tuple[str, str], ...]


def record_publication_gate_policy(
    run_id: str, resolved: ResolvedPublicationGatePolicy
) -> tuple[PublicationGateExecution, ...]:
    """Persist the first protected-base policy seen for this exact leased publication.

    The policy is immutable after creation, so activity retries cannot swap a gate
    definition after the sandbox has begun executing it.
    """

    def operation(
        _integration: object,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> tuple[PublicationGateExecution, ...]:
        policy, created = _get_or_create_policy(lease, publication, resolved)
        if not created:
            _validate_persisted_policy(policy, lease, publication, resolved)
        if policy.status != TaskPublicationGatePolicy.Status.READY:
            raise PublicationGateError("gate_policy_unavailable")
        return tuple(
            PublicationGateExecution(gate_key=_gate_key(gate.label), label=gate.label, argv=gate.argv)
            for gate in _gates_from_policy(policy)
        )

    return with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")


def record_publication_gate_result(
    run_id: str,
    gate: PublicationGateExecution,
    *,
    exit_code: int,
    output: bytes,
) -> None:
    """Store a bounded, opaque execution result under the exact locked policy."""
    bounded_output = output[:_MAX_GATE_OUTPUT_BYTES]
    digest = hashlib.sha256(bounded_output).hexdigest()

    def operation(
        _integration: object,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> tuple[TaskPublicationGatePolicy, TaskPublicationGateLedger]:
        policy = TaskPublicationGatePolicy.objects.for_team(lease.team_id).select_for_update().get(lease_id=lease.id)
        if policy.status != TaskPublicationGatePolicy.Status.READY or not _policy_has_gate(policy, gate):
            raise PublicationGateError("gate_policy_unavailable")
        row, _ = (
            TaskPublicationGateLedger.objects.for_team(lease.team_id)
            .select_for_update()
            .get_or_create(
                policy=policy,
                gate_key=gate.gate_key,
                defaults={
                    "team_id": lease.team_id,
                    "lease": lease,
                    "label": gate.label,
                    "argv": list(gate.argv),
                },
            )
        )
        if row.lease_id != lease.id or row.label != gate.label or row.argv != list(gate.argv):
            raise PublicationGateError("gate_policy_unavailable")
        if row.status == TaskPublicationGateLedger.Status.PASSED:
            return policy, row
        row.attempts += 1
        row.status = TaskPublicationGateLedger.Status.PENDING
        row.started_at = django_timezone.now()
        row.save(update_fields=["attempts", "status", "started_at", "updated_at"])
        return policy, row

    policy, row = with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")
    storage_path = f"tasks/publication-gates/{policy.id}/{row.gate_key}/{digest}.log"
    existing = object_storage.read_bytes(storage_path, missing_ok=True)
    if existing is None:
        object_storage.write(storage_path, bounded_output, {"ContentType": "text/plain; charset=utf-8"})
        existing = object_storage.read_bytes(storage_path, missing_ok=True)
    if existing != bounded_output:
        raise PublicationGateError("publication_gate_output_unavailable")

    def finalize(
        _integration: object,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        _publication: TaskDraftPublication,
    ) -> None:
        current = TaskPublicationGateLedger.objects.for_team(lease.team_id).select_for_update().get(id=row.id)
        if current.policy_id != policy.id or current.lease_id != lease.id:
            raise PublicationGateError("gate_policy_unavailable")
        if current.status == TaskPublicationGateLedger.Status.PASSED:
            return
        current.status = (
            TaskPublicationGateLedger.Status.PASSED if exit_code == 0 else TaskPublicationGateLedger.Status.FAILED
        )
        current.exit_code = exit_code
        current.output_storage_path = storage_path
        current.output_sha256 = digest
        current.output_byte_count = len(bounded_output)
        current.completed_at = django_timezone.now()
        current.save(
            update_fields=[
                "status",
                "exit_code",
                "output_storage_path",
                "output_sha256",
                "output_byte_count",
                "completed_at",
                "updated_at",
            ]
        )

    with_validated_staged_draft_publication(run_id, finalize, mode="in_flight_mutation")


def require_successful_publication_gates(run_id: str) -> None:
    """Broker-side revalidation: model output cannot satisfy a publication gate."""

    def operation(
        _integration: object,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        publication: TaskDraftPublication,
    ) -> None:
        try:
            policy = (
                TaskPublicationGatePolicy.objects.for_team(lease.team_id).select_for_update().get(lease_id=lease.id)
            )
        except TaskPublicationGatePolicy.DoesNotExist as error:
            raise PublicationGateError("gate_policy_unavailable") from error
        if (
            policy.status != TaskPublicationGatePolicy.Status.READY
            or policy.repository != publication.repository
            or policy.base_sha != publication.base_sha
        ):
            raise PublicationGateError("gate_policy_unavailable")
        for gate in _gates_from_policy(policy):
            row = (
                TaskPublicationGateLedger.objects.for_team(lease.team_id)
                .filter(
                    policy_id=policy.id,
                    lease_id=lease.id,
                    gate_key=_gate_key(gate.label),
                    label=gate.label,
                    argv=list(gate.argv),
                    status=TaskPublicationGateLedger.Status.PASSED,
                    exit_code=0,
                )
                .first()
            )
            if row is None:
                raise PublicationGateError("publication_gate_not_passed")

    with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")


def get_publication_gate_status(run_id: str) -> PublicationGateStatus | None:
    def operation(
        _integration: object,
        _task: object,
        _source: object,
        _transition: object,
        _successor: object,
        lease: TaskPublicationLease,
        _publication: TaskDraftPublication,
    ) -> PublicationGateStatus | None:
        policy = TaskPublicationGatePolicy.objects.for_team(lease.team_id).filter(lease_id=lease.id).first()
        if policy is None:
            return None
        if policy.status != TaskPublicationGatePolicy.Status.READY:
            return PublicationGateStatus(overall_status=policy.status, completed_at=None, gates=())
        rows = {
            row.gate_key: row
            for row in TaskPublicationGateLedger.objects.for_team(lease.team_id).filter(policy_id=policy.id)
        }
        gates = tuple(
            (gate.label, row.status if (row := rows.get(_gate_key(gate.label))) is not None else "pending")
            for gate in _gates_from_policy(policy)
        )
        statuses = {status for _, status in gates}
        overall_status = (
            "failed"
            if TaskPublicationGateLedger.Status.FAILED in statuses
            else "passed"
            if statuses == {TaskPublicationGateLedger.Status.PASSED}
            else "pending"
        )
        completed_at = (
            max(row.completed_at for row in rows.values() if row.completed_at is not None)
            if overall_status in {"passed", "failed"} and any(row.completed_at is not None for row in rows.values())
            else None
        )
        return PublicationGateStatus(overall_status=overall_status, completed_at=completed_at, gates=gates)

    try:
        return with_validated_staged_draft_publication(run_id, operation, mode="reconcile_after_expiry")
    except TaskInvalidStateError:
        try:
            return with_validated_staged_draft_publication(run_id, operation, mode="in_flight_mutation")
        except TaskInvalidStateError:
            return None


def _get_or_create_policy(
    lease: TaskPublicationLease, publication: TaskDraftPublication, resolved: ResolvedPublicationGatePolicy
) -> tuple[TaskPublicationGatePolicy, bool]:
    defaults = {
        "team_id": lease.team_id,
        "repository": publication.repository,
        "base_sha": publication.base_sha,
        "source_path": resolved.source_path,
        "source_sha256": resolved.source_sha256,
        "required_gates": [{"label": gate.label, "argv": list(gate.argv)} for gate in resolved.gates],
        "status": resolved.status,
        "reason": resolved.reason,
    }
    try:
        return TaskPublicationGatePolicy.objects.for_team(lease.team_id).get_or_create(lease=lease, defaults=defaults)
    except IntegrityError:
        return TaskPublicationGatePolicy.objects.for_team(lease.team_id).get(lease=lease), False


def _validate_persisted_policy(
    policy: TaskPublicationGatePolicy,
    lease: TaskPublicationLease,
    publication: TaskDraftPublication,
    resolved: ResolvedPublicationGatePolicy,
) -> None:
    expected_gates = [{"label": gate.label, "argv": list(gate.argv)} for gate in resolved.gates]
    if (
        policy.team_id != lease.team_id
        or policy.repository != publication.repository
        or policy.base_sha != publication.base_sha
        or policy.source_path != resolved.source_path
        or policy.source_sha256 != resolved.source_sha256
        or policy.required_gates != expected_gates
        or policy.status != resolved.status
        or policy.reason != resolved.reason
    ):
        raise PublicationGateError("gate_policy_unavailable")


def _gates_from_policy(policy: TaskPublicationGatePolicy) -> tuple[PublicationGateDefinition, ...]:
    parsed: list[PublicationGateDefinition] = []
    for raw in policy.required_gates:
        if not isinstance(raw, dict):
            raise PublicationGateError("gate_policy_unavailable")
        label = raw.get("label")
        argv = raw.get("argv")
        if not isinstance(label, str) or not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
            raise PublicationGateError("gate_policy_unavailable")
        parsed.append(PublicationGateDefinition(label=label, argv=tuple(argv)))
    if not parsed:
        raise PublicationGateError("gate_policy_unavailable")
    return tuple(parsed)


def _policy_has_gate(policy: TaskPublicationGatePolicy, gate: PublicationGateExecution) -> bool:
    return any(
        _gate_key(candidate.label) == gate.gate_key
        and candidate == PublicationGateDefinition(label=gate.label, argv=gate.argv)
        for candidate in _gates_from_policy(policy)
    )


def _gate_key(label: str) -> str:
    return hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()
