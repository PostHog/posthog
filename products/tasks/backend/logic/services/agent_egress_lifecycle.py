from __future__ import annotations

import hashlib
import logging
from contextlib import suppress
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pydantic import BaseModel, ConfigDict

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_probe import (
    AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS,
    AgentEgressProbeConfig,
    AgentEgressProbeIssuer,
)
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.logic.services.modal_sandbox import ModalSandbox
from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user
from products.tasks.backend.models import TaskRun

logger = logging.getLogger(__name__)

STATE_KEY = "agent_egress_probe"


class AgentEgressExecution(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: UUID
    workflow_run_id: str
    config_sha256: str
    previous_execution_id: UUID | None
    expires_at: float
    sandbox_id: str | None = None
    sidecar_id: str | None = None
    capability_refresh_at: float = 0
    closed: bool = False
    closed_execution_ids: tuple[UUID, ...] = ()


class AgentEgressLifecycle:
    def __init__(self, config: AgentEgressProbeConfig, *, execution_id: UUID, workflow_run_id: str) -> None:
        if not settings.DEBUG or settings.SANDBOX_PROVIDER != "MODAL_DOCKER":
            raise ValueError("Egress probes require DEBUG and SANDBOX_PROVIDER=MODAL_DOCKER")
        self.config = config
        self.execution_id = execution_id
        self.workflow_run_id = workflow_run_id
        self.config_sha256 = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
        self.registry = AgentEgressRegistry(region=settings.AGENT_EGRESS_REGION)

    def _run(self, *, locked: bool = False) -> TaskRun:
        runs = TaskRun.objects.select_for_update() if locked else TaskRun.objects
        return runs.get(id=self.config.run_id, team_id=self.config.team_id)

    def _read(self, run: TaskRun) -> AgentEgressExecution:
        state = AgentEgressExecution.model_validate((run.state or {}).get(STATE_KEY))
        if (
            state.execution_id != self.execution_id
            or state.workflow_run_id != self.workflow_run_id
            or state.config_sha256 != self.config_sha256
        ):
            raise ValueError("The egress execution has been replaced")
        return state

    def _save(self, run: TaskRun, state: AgentEgressExecution) -> None:
        TaskRun.update_state_atomic(run.id, updates={STATE_KEY: state.model_dump(mode="json")})

    def _active(self) -> AgentEgressExecution:
        state = self._read(self._run())
        if state.closed or state.expires_at <= timezone.now().timestamp():
            raise ValueError("The egress execution has ended")
        return state

    def _claim(self) -> AgentEgressExecution:
        self.config.eligible_run()
        with transaction.atomic():
            run = self._run(locked=True)
            previous = self.registry.latest(team_id=run.team_id, run_id=run.id)
            raw = (run.state or {}).get(STATE_KEY)
            closed_execution_ids: tuple[UUID, ...] = ()
            if raw:
                existing = AgentEgressExecution.model_validate(raw)
                closed_execution_ids = existing.closed_execution_ids
                if self.execution_id in closed_execution_ids:
                    raise ValueError("The egress execution has ended")
                if existing.execution_id == self.execution_id:
                    self._read(run)
                    raise ValueError("Egress provisioning cannot be retried")
                if not existing.closed and existing.expires_at > timezone.now().timestamp():
                    if (
                        previous is None
                        or previous.execution_id != existing.execution_id
                        or self.registry.lookup(team_id=run.team_id, run_id=run.id, execution_id=existing.execution_id)
                        is not None
                    ):
                        raise ValueError("Another workflow owns this egress probe")
            state = AgentEgressExecution(
                execution_id=self.execution_id,
                workflow_run_id=self.workflow_run_id,
                config_sha256=self.config_sha256,
                previous_execution_id=previous.execution_id if previous else None,
                expires_at=(timezone.now() + timedelta(seconds=self.config.duration_seconds + 180)).timestamp(),
                closed_execution_ids=closed_execution_ids,
            )
            self._save(run, state)
            return state

    def _connect(self, state: AgentEgressExecution) -> ModalEgressProbe:
        if state.sandbox_id is None or state.sidecar_id is None:
            raise ValueError("The egress relay has not been provisioned")
        return ModalEgressProbe.connect(
            sandbox_id=state.sandbox_id,
            sidecar_id=state.sidecar_id,
            endpoint=self.config.endpoint,
            ttl_seconds=self.config.duration_seconds + 180,
        )

    def _renew(self) -> None:
        self._active()
        if (
            self.registry.renew(team_id=self.config.team_id, run_id=self.config.run_id, execution_id=self.execution_id)
            is None
        ):
            raise ValueError("The execution no longer has egress authority")

    def _publish(self, probe: ModalEgressProbe) -> None:
        self._active()
        capability = self.registry.issue_capability(
            team_id=self.config.team_id, run_id=self.config.run_id, execution_id=self.execution_id
        )
        probe.publish_capability(capability)
        self._renew()
        with transaction.atomic():
            run = self._run(locked=True)
            state = self._read(run)
            self._save(
                run,
                state.model_copy(
                    update={
                        "capability_refresh_at": timezone.now().timestamp() + AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS
                    }
                ),
            )

    def prepare(self) -> str:
        state = self._claim()
        config = self.config
        issuer = AgentEgressProbeIssuer(
            certificate=config.client_ca_file.read_bytes(), private_key=config.client_ca_key_file.read_bytes()
        )
        probe = ModalEgressProbe.create(
            name=f"egress-probe-{self.execution_id}",
            relay_image_id=config.relay_image_id,
            endpoint=config.endpoint,
            ttl_seconds=config.duration_seconds + 180,
            dev_proxy_ipv4=config.dev_proxy_ipv4,
        )
        try:
            with transaction.atomic():
                run = self._run(locked=True)
                current = self._read(run)
                if current.closed:
                    raise ValueError("The egress execution has ended")
                self._save(
                    run,
                    current.model_copy(update={"sandbox_id": probe.sandbox.id, "sidecar_id": probe.sidecar.object_id}),
                )
            issued = issuer.issue(probe.certificate_request())
            probe.start_relay(certificate=issued.certificate, server_ca=config.server_ca_file.read_text())
            self._active()
            run = config.eligible_run()
            actor = get_task_run_credential_user(run.task, run.state, raise_on_error=True)
            if actor is None:
                raise ValueError("The run has no eligible actor")
            self.registry.register(
                team_id=config.team_id,
                run_id=config.run_id,
                execution_id=self.execution_id,
                actor_id=actor.id,
                authority=urlsplit(config.endpoint).netloc,
                relay_key_sha256=issued.relay_key_sha256,
                previous_execution_id=state.previous_execution_id,
            )
            self._publish(probe)
            return probe.sandbox.id
        except BaseException:
            try:
                self.close(reason="failed", sandbox_id=probe.sandbox.id)
            except Exception:
                logger.exception("agent_egress_probe_cleanup_failed")
            raise

    def renew(self) -> None:
        self._renew()
        state = self._active()
        if state.capability_refresh_at <= timezone.now().timestamp():
            self._publish(self._connect(state))

    def probe(self) -> dict[int, int]:
        state = self._active()
        result = self._connect(state).probe(count=self.config.requests_per_round, concurrency=self.config.concurrency)
        if set(result) != {204}:
            raise ValueError("The registered probe request failed")
        return result

    def close(self, *, reason: str, sandbox_id: str | None) -> None:
        run = TaskRun.objects.filter(id=self.config.run_id, team_id=self.config.team_id).first()
        raw = (run.state or {}).get(STATE_KEY) if run else None
        if raw:
            state = AgentEgressExecution.model_validate(raw)
            if state.execution_id == self.execution_id and state.workflow_run_id != self.workflow_run_id:
                raise ValueError("Another workflow owns this egress probe")
        try:
            self.registry.revoke(
                team_id=self.config.team_id,
                run_id=self.config.run_id,
                execution_id=self.execution_id,
                revoked_by="egress-probe",
                reason=reason,
            )
        finally:
            try:
                with transaction.atomic():
                    run = (
                        TaskRun.objects.select_for_update()
                        .filter(id=self.config.run_id, team_id=self.config.team_id)
                        .first()
                    )
                    raw = (run.state or {}).get(STATE_KEY) if run else None
                    if run is not None:
                        current = (
                            AgentEgressExecution.model_validate(raw)
                            if raw
                            else AgentEgressExecution(
                                execution_id=self.execution_id,
                                workflow_run_id=self.workflow_run_id,
                                config_sha256=self.config_sha256,
                                previous_execution_id=None,
                                expires_at=timezone.now().timestamp(),
                                sandbox_id=sandbox_id,
                                closed=True,
                            )
                        )
                        if (
                            current.execution_id == self.execution_id
                            and current.workflow_run_id == self.workflow_run_id
                        ):
                            sandbox_id = current.sandbox_id or sandbox_id
                            current = current.model_copy(update={"closed": True})
                        if self.execution_id not in current.closed_execution_ids:
                            current = current.model_copy(
                                update={"closed_execution_ids": (*current.closed_execution_ids, self.execution_id)}
                            )
                        self._save(run, current)
            finally:
                if sandbox_id is not None:
                    with suppress(SandboxNotFoundError):
                        ModalSandbox.get_by_id(sandbox_id).destroy()
