from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from pydantic import BaseModel, ConfigDict, Field

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_probe import (
    AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS,
    AgentEgressProbeConfig,
    AgentEgressProbeIssuer,
)
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user
from products.tasks.backend.models import TaskRun

STATE_KEY = "agent_egress_probe"
MAX_CLOSED_EXECUTIONS = 128


class AgentEgressExecution(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    execution_id: UUID
    workflow_run_id: str
    config_sha256: str
    previous_execution_id: UUID | None
    expires_at: float
    sandbox_id: str | None = None
    sidecar_id: str | None = None
    previous_sandbox_id: str | None = None
    previous_relay_name: str | None = None
    owns_sandbox: bool = True
    capability_refresh_at: float = 0
    closed: bool = False
    closed_executions: dict[str, float] = Field(default_factory=dict)


class AgentEgressLifecycle:
    def __init__(
        self,
        config: AgentEgressProbeConfig,
        *,
        execution_id: UUID,
        workflow_run_id: str,
        provisioning_deadline: float | None = None,
    ) -> None:
        if not settings.DEBUG or settings.SANDBOX_PROVIDER != "MODAL_DOCKER":
            raise ValueError("Egress probes require DEBUG and SANDBOX_PROVIDER=MODAL_DOCKER")
        self.config = config
        self.execution_id = execution_id
        self.workflow_run_id = workflow_run_id
        self.provisioning_deadline = provisioning_deadline
        self.config_sha256 = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
        self.registry = AgentEgressRegistry(region=settings.AGENT_EGRESS_REGION)

    @property
    def relay_name(self) -> str:
        return f"egress-relay-{self.execution_id.hex}" if self.config.sandbox_id else "egress-relay"

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

    def _check_provisioning_deadline(self) -> None:
        now = timezone.now().timestamp()
        if self.provisioning_deadline is None or not now < self.provisioning_deadline <= now + 180:
            raise ValueError("The egress provisioning window has ended")

    def _claim(self) -> AgentEgressExecution:
        self._check_provisioning_deadline()
        now = timezone.now().timestamp()
        self.config.eligible_run()
        with transaction.atomic():
            run = self._run(locked=True)
            previous = self.registry.latest(team_id=run.team_id, run_id=run.id)
            raw = (run.state or {}).get(STATE_KEY)
            closed_executions: dict[str, float] = {}
            previous_sandbox_id = None
            previous_relay_name = None
            if raw:
                existing = AgentEgressExecution.model_validate(raw)
                closed_executions = {key: expiry for key, expiry in existing.closed_executions.items() if expiry > now}
                if str(self.execution_id) in closed_executions:
                    raise ValueError("The egress execution has ended")
                if existing.execution_id == self.execution_id:
                    self._read(run)
                    if existing.closed or existing.expires_at <= now:
                        raise ValueError("The egress execution has ended")
                    if previous is not None and previous.execution_id == self.execution_id:
                        if (
                            self.registry.lookup(team_id=run.team_id, run_id=run.id, execution_id=self.execution_id)
                            is None
                        ):
                            raise ValueError("The execution no longer has egress authority")
                    return existing
                if not existing.closed and existing.expires_at > timezone.now().timestamp():
                    if (
                        previous is None
                        or previous.execution_id != existing.execution_id
                        or self.registry.lookup(team_id=run.team_id, run_id=run.id, execution_id=existing.execution_id)
                        is not None
                    ):
                        raise ValueError("Another workflow owns this egress probe")
                previous_sandbox_id = existing.sandbox_id
                if not existing.owns_sandbox:
                    previous_relay_name = f"egress-relay-{existing.execution_id.hex}"
            if len(closed_executions) >= MAX_CLOSED_EXECUTIONS:
                raise ValueError("Too many recent egress executions")
            state = AgentEgressExecution(
                execution_id=self.execution_id,
                workflow_run_id=self.workflow_run_id,
                config_sha256=self.config_sha256,
                previous_execution_id=previous.execution_id if previous else None,
                expires_at=(timezone.now() + timedelta(seconds=self.config.duration_seconds + 180)).timestamp(),
                previous_sandbox_id=previous_sandbox_id,
                previous_relay_name=previous_relay_name,
                owns_sandbox=self.config.sandbox_id is None,
                closed_executions=closed_executions,
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
            relay_name=self.relay_name,
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
        if state.previous_sandbox_id:
            if state.previous_relay_name:
                ModalEgressProbe.close_relay(state.previous_sandbox_id, state.previous_relay_name)
            else:
                ModalEgressProbe.close_sandbox(state.previous_sandbox_id)
        if state.sandbox_id:
            probe = self._connect(state)
        elif config.sandbox_id:
            probe = ModalEgressProbe.attach(
                sandbox_id=config.sandbox_id,
                relay_name=self.relay_name,
                relay_image_id=config.relay_image_id,
                endpoint=config.endpoint,
                ttl_seconds=max(60, int(state.expires_at - timezone.now().timestamp())),
                dev_proxy_ipv4=config.dev_proxy_ipv4,
            )
        else:
            probe = ModalEgressProbe.create(
                name=f"egress-probe-{self.execution_id}",
                relay_image_id=config.relay_image_id,
                endpoint=config.endpoint,
                ttl_seconds=max(60, int(state.expires_at - timezone.now().timestamp())),
                dev_proxy_ipv4=config.dev_proxy_ipv4,
            )
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
        self._check_provisioning_deadline()
        self.registry.register(
            team_id=config.team_id,
            run_id=config.run_id,
            execution_id=self.execution_id,
            actor_id=actor.id,
            authority=urlsplit(config.endpoint).netloc,
            relay_key_sha256=issued.relay_key_sha256,
            sandbox_id=probe.sandbox.id,
            previous_execution_id=state.previous_execution_id,
        )
        self._check_provisioning_deadline()
        self._publish(probe)
        return probe.sandbox.id

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
                        now = timezone.now().timestamp()
                        closed_executions = {
                            key: expiry for key, expiry in current.closed_executions.items() if expiry > now
                        }
                        if self.provisioning_deadline is not None and self.provisioning_deadline > now:
                            closed_executions[str(self.execution_id)] = self.provisioning_deadline
                        current = current.model_copy(update={"closed_executions": closed_executions})
                        self._save(run, current)
            finally:
                if self.config.sandbox_id:
                    ModalEgressProbe.close_relay(self.config.sandbox_id, self.relay_name)
                elif sandbox_id is not None:
                    ModalEgressProbe.close_sandbox(sandbox_id)
                else:
                    ModalEgressProbe.close_named(f"egress-probe-{self.execution_id}")
