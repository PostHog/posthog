import re
import base64
import ipaddress
from datetime import timedelta
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from posthog.models.team.team import DEPRECATED_ATTRS

from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    AgentEgressTokenPayload,
    _encode_agent_egress_token,
    get_primary_sandbox_jwt_kid,
)
from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user, user_has_current_team_access
from products.tasks.backend.models import AgentEgressRegistration, TaskRun

AGENT_EGRESS_LEASE_DURATION = timedelta(seconds=30)
_TERMINAL_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


def _run_actor_matches(run: TaskRun, actor_id: int) -> bool:
    task = run.task
    if (
        run.is_terminal
        or (run.state or {}).get("cancel_requested_at")
        or task.deleted
        or task.team_id != run.team_id
        or not run.matches_task_ownership(task)
    ):
        return False
    actor = get_task_run_credential_user(task, run.state, raise_on_error=True)
    return (
        actor is not None
        and actor.id == actor_id
        and user_has_current_team_access(actor, task.team, raise_on_error=True)
    )


def _validate_binding(authority: str, relay_key_sha256: str, actor_id: int) -> None:
    host, separator, port = authority.partition(":")
    labels = host.split(".")
    if (
        len(host) > 253
        or (len(labels) < 2 and host != "localhost")
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
        or (
            separator
            and (not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535 or str(int(port)) != port)
        )
    ):
        raise ValueError("Invalid egress authority")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Egress authority must be a hostname")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{43}", relay_key_sha256)
        or base64.urlsafe_b64encode(base64.urlsafe_b64decode(relay_key_sha256 + "=")).decode().rstrip("=")
        != relay_key_sha256
    ):
        raise ValueError("Invalid relay key fingerprint")
    if not 0 < actor_id < 2**63:
        raise ValueError("Invalid egress actor")


class AgentEgressRegistry:
    def __init__(self, *, region: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", region):
            raise ImproperlyConfigured("Invalid egress region")
        self.region = region

    def latest(self, *, team_id: int, run_id: UUID) -> AgentEgressRegistration | None:
        return (
            AgentEgressRegistration.objects.for_team(team_id)
            .filter(task_run_id=run_id, task_run__team_id=team_id, region=self.region)
            .order_by("-id")
            .first()
        )

    def lookup(self, *, team_id: int, run_id: UUID, execution_id: UUID) -> AgentEgressRegistration | None:
        registration = (
            AgentEgressRegistration.objects.for_team(team_id)
            .select_related("task_run__task__created_by", "task_run__task__team")
            .defer(*(f"task_run__task__team__{field}" for field in DEPRECATED_ATTRS))
            .filter(
                task_run_id=run_id,
                task_run__team_id=team_id,
                execution_id=execution_id,
                region=self.region,
                revoked=False,
                lease_expires_at__gt=timezone.now(),
            )
            .exclude(task_run__status__in=_TERMINAL_STATUSES)
            .first()
        )
        if registration is None or not _run_actor_matches(registration.task_run, registration.actor_id):
            return None
        if (
            registration.task_ownership_version != registration.task_run.ownership_version
            or registration.lease_expires_at <= timezone.now()
        ):
            return None
        return registration

    def register(
        self,
        *,
        team_id: int,
        run_id: UUID,
        execution_id: UUID,
        actor_id: int,
        authority: str,
        relay_key_sha256: str,
        previous_execution_id: UUID | None = None,
    ) -> AgentEgressRegistration:
        _validate_binding(authority, relay_key_sha256, actor_id)
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)
            if not _run_actor_matches(run, actor_id):
                raise ValueError("Task run actor is not authorized")
            registrations = AgentEgressRegistration.objects.for_team(team_id).filter(task_run_id=run.id)
            existing = registrations.filter(execution_id=execution_id).first()
            now = timezone.now()
            if existing is not None:
                if (
                    existing.revoked
                    or existing.lease_expires_at <= now
                    or existing.region != self.region
                    or existing.actor_id != actor_id
                    or existing.authority != authority
                    or existing.relay_key_sha256 != relay_key_sha256
                    or existing.task_ownership_version != run.ownership_version
                ):
                    raise ValueError("Execution registration cannot be reused")
                return existing
            current = registrations.order_by("-id").first()
            if (current.execution_id if current else None) != previous_execution_id:
                raise ValueError("Execution registration has changed")
            if current is not None:
                if current.region != self.region:
                    raise ValueError("Execution region cannot change")
                registrations.filter(execution_id=current.execution_id).update(revoked=True)
            return registrations.create(
                team_id=team_id,
                task_run=run,
                execution_id=execution_id,
                region=self.region,
                actor_id=actor_id,
                actor_epoch=current.actor_epoch + 1 if current else 1,
                task_ownership_version=run.ownership_version,
                authority=authority,
                relay_key_sha256=relay_key_sha256,
                lease_expires_at=now + AGENT_EGRESS_LEASE_DURATION,
            )

    def issue_capability(self, *, team_id: int, run_id: UUID, execution_id: UUID) -> str:
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)
            registration = self.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id)
            if registration is None:
                raise ValueError("Execution registration is not active")
            if SANDBOX_JWT_STATE_KID_KEY not in (run.state or {}):
                run.state = {**(run.state or {}), SANDBOX_JWT_STATE_KID_KEY: get_primary_sandbox_jwt_kid()}
                run.save(update_fields=["state"])
            return _encode_agent_egress_token(
                run,
                AgentEgressTokenPayload(
                    actor_id=registration.actor_id,
                    actor_epoch=registration.actor_epoch,
                    execution_id=registration.execution_id,
                    relay_key_sha256=registration.relay_key_sha256,
                ),
            )

    def renew(self, *, team_id: int, run_id: UUID, execution_id: UUID) -> AgentEgressRegistration | None:
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().filter(id=run_id, team_id=team_id).first()
            if run is None or run.status in _TERMINAL_STATUSES:
                return None
            registration = self.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id)
            if registration is None:
                return None
            now = timezone.now()
            if registration.lease_expires_at <= now:
                return None
            registration.lease_expires_at = now + AGENT_EGRESS_LEASE_DURATION
            registration.save(update_fields=["lease_expires_at"])
            return registration

    def revoke(self, *, team_id: int, run_id: UUID, execution_id: UUID) -> bool:
        with transaction.atomic():
            run = TaskRun.objects.select_for_update().filter(id=run_id, team_id=team_id).first()
            if run is None:
                return False
            return bool(
                AgentEgressRegistration.objects.for_team(team_id)
                .filter(task_run_id=run.id, execution_id=execution_id, region=self.region, revoked=False)
                .update(revoked=True)
            )
