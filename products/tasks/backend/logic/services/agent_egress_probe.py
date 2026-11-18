from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
    from products.tasks.backend.models import AgentEgressRegistration

AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS = 180


class AgentEgressProbeStoppedError(RuntimeError):
    pass


class AgentEgressProbeSession:
    def __init__(
        self,
        *,
        registry: AgentEgressRegistry,
        team_id: int,
        run_id: UUID,
        actor_id: int,
        authority: str,
        relay_key_sha256: str,
        publish_capability: Callable[[str], None],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.team_id = team_id
        self.run_id = run_id
        self.actor_id = actor_id
        self.authority = authority
        self.relay_key_sha256 = relay_key_sha256
        self.execution_id = uuid4()
        self._publish_capability = publish_capability
        self._monotonic = monotonic
        self._refresh_at = 0.0
        self._started = False
        self._stopped = False

    def _renew(self) -> AgentEgressRegistration:
        registration = self.registry.renew(team_id=self.team_id, run_id=self.run_id, execution_id=self.execution_id)
        if registration is None:
            raise AgentEgressProbeStoppedError("The execution no longer has egress authority")
        return registration

    def _publish(self) -> AgentEgressRegistration:
        capability = self.registry.issue_capability(
            team_id=self.team_id, run_id=self.run_id, execution_id=self.execution_id
        )
        self._publish_capability(capability)
        registration = self._renew()
        self._refresh_at = self._monotonic() + AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS
        return registration

    def stop(self) -> None:
        self._stopped = True
        if self._started:
            self.registry.revoke(team_id=self.team_id, run_id=self.run_id, execution_id=self.execution_id)

    def start(self) -> AgentEgressRegistration:
        if self._started or self._stopped:
            raise AgentEgressProbeStoppedError("Create a new probe session to enroll a new execution")
        self._started = True
        try:
            previous = self.registry.latest(team_id=self.team_id, run_id=self.run_id)
            self.registry.register(
                team_id=self.team_id,
                run_id=self.run_id,
                execution_id=self.execution_id,
                actor_id=self.actor_id,
                authority=self.authority,
                relay_key_sha256=self.relay_key_sha256,
                previous_execution_id=previous.execution_id if previous else None,
            )
            return self._publish()
        except BaseException:
            with suppress(Exception):
                self.stop()
            raise

    def tick(self) -> AgentEgressRegistration:
        if not self._started or self._stopped:
            raise AgentEgressProbeStoppedError("The probe session is not active")
        try:
            registration = self._renew()
            if self._monotonic() >= self._refresh_at:
                return self._publish()
            return registration
        except BaseException:
            with suppress(Exception):
                self.stop()
            raise
