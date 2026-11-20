from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from django.conf import settings

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from pydantic import BaseModel, ConfigDict, Field

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user, user_has_current_team_access
from products.tasks.backend.logic.services.sandbox_config import (
    agent_egress_staging_environment,
    agent_egress_staging_probe_enabled,
)
from products.tasks.backend.models import TaskRun

AGENT_EGRESS_CAPABILITY_REFRESH_SECONDS = 180


class AgentEgressProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: int = Field(gt=0)
    run_id: UUID
    endpoint: str
    relay_image_id: str
    server_ca_file: Path
    client_ca_file: Path
    client_ca_key_file: Path
    duration_seconds: int = Field(default=60, ge=1, le=600)
    concurrency: int = Field(default=4, ge=1, le=32)
    requests_per_round: int = Field(default=16, ge=1, le=256)
    dev_proxy_ipv4: str | None = None
    sandbox_id: str | None = None

    @staticmethod
    def require_environment(*, cleanup: bool = False) -> None:
        if (
            not (settings.DEBUG and settings.SANDBOX_PROVIDER == "MODAL_DOCKER")
            and not agent_egress_staging_probe_enabled()
            and not (cleanup and agent_egress_staging_environment())
        ):
            raise ValueError("Egress probes require DEBUG and SANDBOX_PROVIDER=MODAL_DOCKER, or a staging probe opt-in")

    def validate_controller(self, *, cleanup: bool = False) -> None:
        self.require_environment(cleanup=cleanup)
        if agent_egress_staging_environment() and (
            (not cleanup and str(self.run_id) != settings.AGENT_EGRESS_STAGING_PROBE_RUN_ID)
            or self.sandbox_id is not None
            or self.dev_proxy_ipv4 is not None
        ):
            raise ValueError("Staging probes require the selected run, a fresh VM and no tunnel override")

    @classmethod
    def load(cls, path: Path, *, cleanup: bool = False) -> AgentEgressProbeConfig:
        cls.require_environment(cleanup=cleanup)
        if not settings.AGENT_EGRESS_PROBE_CONFIG_DIR:
            raise ValueError("Set AGENT_EGRESS_PROBE_CONFIG_DIR to a dedicated probe configuration directory")
        try:
            directory = Path(settings.AGENT_EGRESS_PROBE_CONFIG_DIR).resolve(strict=True)
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(directory):
                raise ValueError("The probe configuration is outside its directory")
            config = cls.model_validate_json(resolved.read_bytes())
            config.validate_controller(cleanup=cleanup)
            return config
        except (OSError, ValueError):
            raise ValueError("Invalid egress probe configuration") from None

    def eligible_run(self) -> TaskRun:
        self.validate_controller()
        run = TaskRun.objects.select_related("task__created_by", "task__team").get(id=self.run_id, team_id=self.team_id)
        if (
            run.is_terminal
            or run.environment != TaskRun.Environment.CLOUD
            or run.task.deleted
            or run.task.team_id != run.team_id
            or not run.matches_task_ownership(run.task)
            or (run.state or {}).get("cancel_requested_at")
        ):
            raise ValueError("Use an active development run without repositories or an existing sandbox")
        if self.sandbox_id is None:
            if (
                run.task.repository
                or run.task.repositories
                or any((run.state or {}).get(key) for key in ("sandbox_id", "sandbox_environment_id"))
            ):
                raise ValueError("Use an active development run without repositories or an existing sandbox")
        elif (run.state or {}).get("sandbox_id") != self.sandbox_id or (run.state or {}).get(
            "sandbox_backend", "modal"
        ) != "modal":
            raise ValueError("The observed sandbox does not belong to this run")
        actor = get_task_run_credential_user(run.task, run.state, raise_on_error=True)
        if actor is None or not user_has_current_team_access(actor, run.task.team, raise_on_error=True):
            raise ValueError("The run has no eligible actor")
        return run


@frozen
class AgentEgressProbeCertificate:
    certificate: str
    relay_key_sha256: str


class AgentEgressProbeIssuer:
    def __init__(self, *, certificate: bytes, private_key: bytes) -> None:
        self.certificate = x509.load_pem_x509_certificate(certificate)
        key = serialization.load_pem_private_key(private_key, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError("The development issuer requires an RSA key of at least 2048 bits")
        self.key = key
        if self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ) != self.certificate.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ):
            raise ValueError("The development issuer certificate and key do not match")
        if not self.certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("The development issuer certificate must be a CA")

    def issue(self, csr_pem: str) -> AgentEgressProbeCertificate:
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        public_key = csr.public_key()
        if not csr.is_signature_valid or not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
            raise ValueError("Invalid relay certificate request")
        now = datetime.now(UTC)
        if not self.certificate.not_valid_before_utc <= now < self.certificate.not_valid_after_utc:
            raise ValueError("The development issuer certificate is not valid")
        certificate = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self.certificate.subject)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(seconds=3))
            .not_valid_after(min(now + timedelta(minutes=15), self.certificate.not_valid_after_utc))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=True)
            .sign(self.key, hashes.SHA256())
        )
        spki = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        fingerprint = base64.urlsafe_b64encode(hashlib.sha256(spki).digest()).decode().rstrip("=")
        return AgentEgressProbeCertificate(
            certificate=certificate.public_bytes(serialization.Encoding.PEM).decode(), relay_key_sha256=fingerprint
        )
