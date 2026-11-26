from __future__ import annotations

from pathlib import Path
from uuid import UUID

from django.conf import settings

from pydantic import BaseModel, ConfigDict, Field

from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig, read_agent_egress_config
from products.tasks.backend.logic.services.sandbox_config import (
    AGENT_EGRESS_DOMAIN_PATTERN,
    agent_egress_enrollment_enabled,
)


class AgentEgressEnrollmentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint_domain: str = Field(max_length=210, pattern=rf"^{AGENT_EGRESS_DOMAIN_PATTERN}$")
    region: str
    relay_image_id: str
    server_ca_file: Path
    client_ca_file: Path
    client_ca_key_file: Path
    renew_relay_certificate: bool = False
    maintain_for_run: bool = False
    publish_git_read_grant: bool = False
    route_git_reads: bool = False
    duration_seconds: int = Field(default=360, ge=1, le=600)
    concurrency: int = Field(default=1, ge=1, le=32)
    requests_per_round: int = Field(default=1, ge=1, le=256)

    @classmethod
    def load(cls) -> AgentEgressEnrollmentConfig:
        if not agent_egress_enrollment_enabled():
            raise ValueError("Agent egress enrollment is disabled")
        try:
            config = cls.model_validate_json(read_agent_egress_config(Path(settings.AGENT_EGRESS_ENROLLMENT_CONFIG)))
            if config.maintain_for_run and not config.renew_relay_certificate:
                raise ValueError("Run-lifetime maintenance requires certificate renewal")
            if config.route_git_reads and not (config.publish_git_read_grant and config.maintain_for_run):
                raise ValueError("Git routing requires grant publication and run-lifetime maintenance")
            if not config.region or config.region != settings.AGENT_EGRESS_REGION:
                raise ValueError("Egress region mismatch")
            return config
        except (OSError, ValueError):
            raise ValueError("Invalid agent egress enrollment configuration") from None


class AgentEgressRunConfig(AgentEgressProbeConfig):
    publish_git_read_grant: bool = False
    route_git_reads: bool = False

    @classmethod
    def for_run(cls, *, team_id: int, run_id: UUID, sandbox_id: str) -> AgentEgressRunConfig:
        config = AgentEgressEnrollmentConfig.load()
        if not sandbox_id:
            raise ValueError("Agent egress enrollment requires a provisioned sandbox")
        return cls(
            **config.model_dump(exclude={"endpoint_domain", "region"}),
            team_id=team_id,
            run_id=run_id,
            sandbox_id=sandbox_id,
            endpoint=f"https://run-{run_id.hex}.{config.endpoint_domain}",
        )

    def validate_controller(self, *, cleanup: bool = False) -> None:
        if self.sandbox_id is None or self.dev_proxy_ipv4 is not None:
            raise ValueError("Agent egress enrollment requires an attached relay without a tunnel override")
        current = self.for_run(team_id=self.team_id, run_id=self.run_id, sandbox_id=self.sandbox_id)
        if self != current:
            raise ValueError("The agent egress enrollment configuration has changed")
