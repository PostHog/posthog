from __future__ import annotations

import sys
import time
import base64
import hashlib
import logging
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID
from pydantic import BaseModel, ConfigDict, Field

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeSession
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user, user_has_current_team_access
from products.tasks.backend.models import TaskRun

logger = logging.getLogger(__name__)


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


class AgentEgressProbeRunner:
    def __init__(self, config: AgentEgressProbeConfig, *, report: Callable[[dict[str, object]], None]) -> None:
        self.config = config
        self.report = report

    def _probe(self, probe: ModalEgressProbe, session: AgentEgressProbeSession) -> dict[int, int]:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            pending = executor.submit(
                probe.probe, count=self.config.requests_per_round, concurrency=self.config.concurrency
            )
            while True:
                try:
                    return pending.result(timeout=10)
                except TimeoutError:
                    if pending.done():
                        return pending.result()
                    session.tick()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def run(self) -> None:
        if not settings.DEBUG or settings.SANDBOX_PROVIDER != "MODAL_DOCKER":
            raise ValueError("Egress probes require DEBUG and SANDBOX_PROVIDER=MODAL_DOCKER")
        config = self.config
        run = TaskRun.objects.select_related("task__created_by", "task__team").get(
            id=config.run_id, team_id=config.team_id
        )
        if (
            run.is_terminal
            or run.environment != TaskRun.Environment.CLOUD
            or run.task.deleted
            or run.task.team_id != run.team_id
            or not run.matches_task_ownership(run.task)
            or run.task.repository
            or run.task.repositories
            or any(
                (run.state or {}).get(key) for key in ("sandbox_id", "sandbox_environment_id", "cancel_requested_at")
            )
        ):
            raise ValueError("Use an active development run without repositories or an existing sandbox")
        actor = get_task_run_credential_user(run.task, run.state, raise_on_error=True)
        if actor is None or not user_has_current_team_access(actor, run.task.team, raise_on_error=True):
            raise ValueError("The run has no eligible actor")
        issuer = AgentEgressProbeIssuer(
            certificate=config.client_ca_file.read_bytes(), private_key=config.client_ca_key_file.read_bytes()
        )
        registry = AgentEgressRegistry(region=settings.AGENT_EGRESS_REGION)
        server_ca = config.server_ca_file.read_text()
        probe = ModalEgressProbe.create(
            name=f"egress-probe-{run.id}",
            relay_image_id=config.relay_image_id,
            endpoint=config.endpoint,
            ttl_seconds=config.duration_seconds + 180,
            dev_proxy_ipv4=config.dev_proxy_ipv4,
        )
        session: AgentEgressProbeSession | None = None
        try:
            issued = issuer.issue(probe.certificate_request())
            probe.start_relay(certificate=issued.certificate, server_ca=server_ca)
            session = AgentEgressProbeSession(
                registry=registry,
                team_id=run.team_id,
                run_id=run.id,
                actor_id=actor.id,
                authority=urlsplit(config.endpoint).netloc,
                relay_key_sha256=issued.relay_key_sha256,
                publish_capability=probe.publish_capability,
            )
            session.start()
            self.report({"sandbox_id": probe.sandbox.id, "execution_id": str(session.execution_id)})
            deadline = time.monotonic() + config.duration_seconds
            counts: Counter[int] = Counter()
            while time.monotonic() < deadline:
                session.tick()
                result = self._probe(probe, session)
                counts.update(result)
                self.report({"statuses": result})
                if set(result) != {204}:
                    raise RuntimeError("The registered probe request failed")
                time.sleep(max(0, min(10, deadline - time.monotonic())))
            self.report({"total_statuses": dict(counts)})
        finally:
            active_error = sys.exception()
            failures: list[Exception] = []
            for cleanup in ([session.stop] if session is not None else []) + [probe.close]:
                try:
                    cleanup()
                except Exception as error:
                    failures.append(error)
            if failures:
                if active_error is None:
                    raise failures[0]
                logger.warning("agent_egress_probe_cleanup_failed", extra={"failure_count": len(failures)})
