from __future__ import annotations

import json
import base64
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from inspect import unwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from uuid import UUID, uuid4

import time_machine
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from structlog.testing import capture_logs
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION
from products.tasks.backend.logic.services.agent_egress_enrollment import (
    AgentEgressEnrollmentConfig,
    AgentEgressRunConfig,
)
from products.tasks.backend.logic.services.agent_egress_lifecycle import (
    STATE_KEY,
    AgentEgressLifecycle,
    AgentEgressOwnershipConflict,
    AgentEgressRunEnded,
)
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeCertificate, AgentEgressProbeConfig
from products.tasks.backend.logic.services.agent_egress_probe_runner import AgentEgressProbeRunner
from products.tasks.backend.logic.services.connection_token import reset_sandbox_jwt_key_cache
from products.tasks.backend.logic.services.modal_egress_probe import (
    AgentEgressCertificateDeliveryError,
    ModalEgressProbe,
)
from products.tasks.backend.models import AgentEgressRegistration, Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.agent_egress import (
    AgentEgressCleanupInput,
    AgentEgressExecutionInput,
    AgentEgressProbeInput,
    _prepare,
    _probe,
    cleanup_agent_egress,
    renew_agent_egress,
)


class FakeIssuer:
    def __init__(self, *, certificate: bytes, private_key: bytes) -> None:
        pass

    def issue(self, csr: str, *, relay_key_sha256: str | None = None) -> AgentEgressProbeCertificate:
        fingerprint = base64.urlsafe_b64encode(hashlib.sha256(csr.encode()).digest()).decode().rstrip("=")
        if relay_key_sha256 is not None and relay_key_sha256 != fingerprint:
            raise ValueError("The relay certificate key has changed")
        return AgentEgressProbeCertificate(
            certificate=f"signed:{csr}:{timezone.now().timestamp()}",
            relay_key_sha256=fingerprint,
            expires_at=timezone.now() + timedelta(minutes=15),
        )


class FakeProbe:
    def __init__(self, *, sandbox: FakeProbe | None = None) -> None:
        self.id = f"sb-{uuid4()}"
        self.object_id = f"sc-{uuid4()}"
        self.sandbox = sandbox or self
        self.sidecar = self
        self.destroyed = False
        self.status = 204
        self.published: list[str] = []
        self.on_publish: Callable[[], None] = lambda: None
        self.on_start: Callable[[], None] = lambda: None
        self.on_probe: Callable[[], None] = lambda: None
        self.certificates: list[str] = []
        self.on_certificate: Callable[[], None] = lambda: None
        self.on_csr: Callable[[], None] = lambda: None

    def certificate_request(self) -> str:
        self.on_csr()
        return self.object_id

    def start_relay(self, *, certificate: str, server_ca: str, client_ca: str | None = None) -> None:
        self.certificates.append(certificate)
        self.on_start()

    def renew_certificate(self, certificate: str) -> None:
        self.on_certificate()
        self.certificates.append(certificate)

    def publish_capability(self, capability: str) -> None:
        self.published.append(capability)
        self.on_publish()

    def probe(self, *, count: int, concurrency: int) -> dict[int, int]:
        self.on_probe()
        return {self.status: count}

    def destroy(self) -> None:
        self.destroyed = True

    def close(self) -> None:
        self.destroy()


@override_settings(DEBUG=True, SANDBOX_PROVIDER="MODAL_DOCKER", AGENT_EGRESS_REGION="test-us")
class TestAgentEgressLifecycle(TestCase):
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    actor: ClassVar[User]
    task_run: ClassVar[TaskRun]
    signing_key: ClassVar[str]
    verification_key: ClassVar[str]

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Egress lifecycle tests")
        cls.team = Team.objects.create(organization=organization, name="Egress")
        cls.other_team = Team.objects.create(organization=organization, name="Other")
        cls.actor = User.objects.create(email="lifecycle@example.com")
        OrganizationMembership.objects.create(organization=organization, user=cls.actor)
        task = Task.objects.create(team=cls.team, created_by=cls.actor, title="Synthetic lifecycle")
        cls.task_run = TaskRun.objects.create(team=cls.team, task=task, status=TaskRun.Status.IN_PROGRESS)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.signing_key = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        cls.verification_key = (
            key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

    def setUp(self) -> None:
        travel = time_machine.travel("2026-11-17T12:00:00Z", tick=False)
        self.clock = travel.start()
        self.addCleanup(travel.stop)
        self.enterContext(
            override_settings(SANDBOX_JWT_PRIVATE_KEY=self.signing_key, SANDBOX_JWT_PRIVATE_KEY_SECONDARY="")
        )
        reset_sandbox_jwt_key_cache()
        self.addCleanup(reset_sandbox_jwt_key_cache)
        directory = Path(self.enterContext(TemporaryDirectory()))
        material = directory / "issuer.pem"
        material.write_text("synthetic issuer material")
        self.config = AgentEgressProbeConfig(
            team_id=self.team.id,
            run_id=self.task_run.id,
            endpoint="https://run-a.egress.example.com",
            relay_image_id="im-synthetic-relay",
            server_ca_file=material,
            client_ca_file=material,
            client_ca_key_file=material,
            duration_seconds=360,
        )
        self.execution_id = uuid4()
        self.probes: dict[str, FakeProbe] = {}
        self.named_probes: dict[str, FakeProbe] = {}
        self.attached_relays: dict[tuple[str, str], FakeProbe] = {}
        self.deadlines: dict[UUID, float] = {}
        self.sandbox_expires_at: float | None = None
        self.on_create: Callable[[], None] = lambda: None
        self.on_start: Callable[[], None] = lambda: None
        self.on_publish: Callable[[], None] = lambda: None
        self.enterContext(
            patch("products.tasks.backend.logic.services.agent_egress_lifecycle.AgentEgressProbeIssuer", FakeIssuer)
        )
        self.enterContext(patch.object(ModalEgressProbe, "create", side_effect=self.create_probe))
        self.enterContext(patch.object(ModalEgressProbe, "attach", side_effect=self.attach_probe))
        self.enterContext(patch.object(ModalEgressProbe, "connect", side_effect=self.connect_probe))
        self.enterContext(patch.object(ModalEgressProbe, "close_sandbox", side_effect=self.close_probe))
        self.enterContext(patch.object(ModalEgressProbe, "close_named", side_effect=self.close_named_probe))
        self.enterContext(patch.object(ModalEgressProbe, "close_relay", side_effect=self.close_relay))

    def close_probe(self, sandbox_id: str) -> None:
        probe = self.probes.get(sandbox_id)
        if probe:
            probe.destroy()

    def close_named_probe(self, name: str) -> None:
        probe = self.named_probes.get(name)
        if probe:
            probe.destroy()

    def close_relay(self, sandbox_id: str, relay_name: str) -> None:
        relay = self.attached_relays.get((sandbox_id, relay_name))
        if relay:
            relay.destroy()

    def create_probe(
        self, *, name: str, relay_image_id: str, endpoint: str, ttl_seconds: int, dev_proxy_ipv4: str | None
    ) -> FakeProbe:
        probe = self.named_probes.get(name)
        if probe is None:
            probe = FakeProbe()
            probe.on_publish = self.on_publish
            probe.on_start = self.on_start
            self.probes[probe.id] = probe
            self.named_probes[name] = probe
        if probe.destroyed:
            raise ValueError("The egress VM has ended")
        self.on_create()
        return probe

    def attach_probe(
        self,
        *,
        sandbox_id: str,
        relay_name: str,
        relay_image_id: str,
        endpoint: str,
        ttl_seconds: int,
        dev_proxy_ipv4: str | None,
    ) -> FakeProbe:
        key = (sandbox_id, relay_name)
        if key not in self.attached_relays:
            self.attached_relays[key] = FakeProbe(sandbox=self.probes[sandbox_id])
            self.attached_relays[key].on_start = self.on_start
            self.attached_relays[key].on_publish = self.on_publish
        return self.attached_relays[key]

    def connect_probe(
        self, *, sandbox_id: str, sidecar_id: str, endpoint: str, ttl_seconds: int, relay_name: str
    ) -> FakeProbe:
        probe = (
            self.probes[sandbox_id] if relay_name == "egress-relay" else self.attached_relays[(sandbox_id, relay_name)]
        )
        if probe.destroyed or probe.object_id != sidecar_id:
            raise RuntimeError("The relay is unavailable")
        return probe

    def controller(
        self, *, execution_id: UUID | None = None, workflow_run_id: str = "workflow-a"
    ) -> AgentEgressLifecycle:
        execution_id = execution_id or self.execution_id
        return AgentEgressLifecycle(
            self.config,
            execution_id=execution_id,
            workflow_run_id=workflow_run_id,
            provisioning_deadline=self.deadlines.setdefault(execution_id, timezone.now().timestamp() + 180),
            sandbox_expires_at=self.sandbox_expires_at,
        )

    def registration(self, execution_id: UUID | None = None) -> AgentEgressRegistration:
        return AgentEgressRegistration.objects.for_team(self.team.id).get(
            execution_id=execution_id or self.execution_id
        )

    def enroll_run(self) -> FakeProbe:
        sandbox = FakeProbe()
        self.probes[sandbox.id] = sandbox
        TaskRun.update_state_atomic(self.task_run.id, updates={"sandbox_id": sandbox.id, "sandbox_backend": "modal"})
        directory = self.config.client_ca_file.parent
        path = directory / "enrollment.json"
        path.write_text(
            AgentEgressEnrollmentConfig(
                endpoint_domain="egress.example.com",
                region="test-us",
                relay_image_id=self.config.relay_image_id,
                server_ca_file=self.config.server_ca_file,
                client_ca_file=self.config.client_ca_file,
                client_ca_key_file=self.config.client_ca_key_file,
                renew_relay_certificate=self.config.renew_relay_certificate,
                maintain_for_run=self.config.maintain_for_run,
                duration_seconds=self.config.duration_seconds,
            ).model_dump_json()
        )
        self.enterContext(
            override_settings(
                DEBUG=False,
                CLOUD_DEPLOYMENT="US",
                SANDBOX_PROVIDER="modal",
                AGENT_EGRESS_PROBE_CONFIG_DIR=str(directory),
                AGENT_EGRESS_ENROLLMENT_CONFIG=str(path),
            )
        )
        self.config = AgentEgressRunConfig.for_run(team_id=self.team.id, run_id=self.task_run.id, sandbox_id=sandbox.id)
        return sandbox

    @parameterized.expand([("development",), ("staging",), ("enrollment",)])
    def test_new_worker_renews_and_refreshes_the_existing_execution(self, environment: str) -> None:
        if environment == "staging":
            self.enterContext(
                override_settings(
                    DEBUG=False,
                    TEST=False,
                    CLOUD_DEPLOYMENT="DEV",
                    SANDBOX_PROVIDER="modal",
                    AGENT_EGRESS_STAGING_PROBE_RUN_ID=str(self.task_run.id),
                )
            )
        elif environment == "enrollment":
            self.enroll_run()
        TaskRun.update_state_atomic(self.task_run.id, updates={"unrelated": "preserved"})
        sandbox_id = self.controller().prepare()
        registration = self.registration()
        if environment == "enrollment":
            self.assertEqual(registration.authority, f"run-{self.task_run.id.hex}.egress.example.com")
        self.assertEqual(self.controller().prepare(), sandbox_id)
        self.assertEqual(self.registration().relay_key_sha256, registration.relay_key_sha256)
        probe = (
            self.attached_relays[(sandbox_id, self.controller().relay_name)]
            if environment == "enrollment"
            else self.probes[sandbox_id]
        )
        published_before_refresh = len(probe.published)
        for _ in range(18):
            self.clock.shift(10)
            self.controller().renew()
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(self.registration().lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        self.assertEqual(len(probe.published), published_before_refresh + 1)
        claims = jwt.decode(
            probe.published[-1],
            self.verification_key,
            algorithms=["RS256"],
            audience="posthog:agent_egress",
        )
        self.assertEqual(claims["execution_id"], str(self.execution_id))
        self.assertEqual(claims["actor_id"], self.actor.id)
        self.assertEqual(claims["relay_key_sha256"], self.registration().relay_key_sha256)
        self.assertEqual(claims["actor_epoch"], self.registration().actor_epoch)
        self.assertEqual(claims["exp"], int(timezone.now().timestamp()) + 300)
        self.assertNotEqual(probe.published[0], probe.published[-1])
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state["unrelated"], "preserved")
        self.assertEqual(self.task_run.state[STATE_KEY]["sandbox_id"], sandbox_id)
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})
        self.controller().close(reason="completed", sandbox_id=sandbox_id)
        self.assertTrue(self.registration().revoked)
        self.assertTrue(probe.destroyed)
        self.assertEqual(self.probes[sandbox_id].destroyed, environment != "enrollment")

    @parameterized.expand([("disabled", False), ("enabled", True)])
    def test_certificate_renewal_survives_a_worker_restart(self, _name: str, enabled: bool) -> None:
        self.config = self.config.model_copy(update={"renew_relay_certificate": enabled, "duration_seconds": 600})
        sandbox = self.enroll_run()
        sandbox_id = self.controller().prepare()
        probe = self.attached_relays[(sandbox.id, self.controller().relay_name)]
        original = probe.certificates[0]
        registration = self.registration()
        for _ in range(44):
            self.clock.shift(10)
            self.controller().renew()
        self.assertEqual(probe.certificates, [original])
        self.clock.shift(10)
        self.controller().renew()
        self.assertEqual(len(probe.certificates), 2 if enabled else 1)
        if enabled:
            self.assertNotEqual(original, probe.certificates[-1])
            self.task_run.refresh_from_db()
            self.assertEqual(self.task_run.state[STATE_KEY]["certificate_refresh_at"], timezone.now().timestamp() + 450)
        self.assertEqual(self.registration().relay_key_sha256, registration.relay_key_sha256)
        self.assertEqual(self.registration().actor_epoch, registration.actor_epoch)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})
        self.controller().close(reason="completed", sandbox_id=sandbox_id)

    @parameterized.expand([("delivery",), ("revoked_during_csr",), ("changed_key",)])
    def test_certificate_renewal_failure_does_not_advance_the_deadline(self, failure: str) -> None:
        self.config = self.config.model_copy(update={"renew_relay_certificate": True, "duration_seconds": 600})
        sandbox_id = self.controller().prepare()
        probe = self.probes[sandbox_id]
        for _ in range(44):
            self.clock.shift(10)
            self.controller().renew()
        self.task_run.refresh_from_db()
        refresh_at = self.task_run.state[STATE_KEY]["certificate_refresh_at"]

        def refuse_delivery() -> None:
            raise RuntimeError("Reload not acknowledged")

        def revoke_during_csr() -> None:
            self.controller().registry.revoke(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )

        if failure == "delivery":
            probe.on_certificate = refuse_delivery
        elif failure == "revoked_during_csr":
            probe.on_csr = revoke_during_csr
        else:
            self.registration().delete()
            controller = self.controller()
            controller.registry.register(
                team_id=self.team.id,
                run_id=self.task_run.id,
                execution_id=self.execution_id,
                actor_id=self.actor.id,
                authority=self.config.endpoint.removeprefix("https://"),
                relay_key_sha256=base64.urlsafe_b64encode(hashlib.sha256(b"other key").digest()).decode().rstrip("="),
                sandbox_id=sandbox_id,
            )
        self.clock.shift(10)
        with self.assertRaises(RuntimeError if failure == "delivery" else ValueError):
            self.controller().renew()
        self.assertEqual(len(probe.certificates), 1)
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["certificate_refresh_at"], refresh_at)
        if failure == "delivery":
            probe.on_certificate = lambda: None
            self.controller().renew()
            self.assertEqual(len(probe.certificates), 2)
        self.controller().close(reason="failed", sandbox_id=sandbox_id)

    def test_existing_config_hash_can_renew_without_certificate_opt_in(self) -> None:
        self.controller().prepare()
        self.task_run.refresh_from_db()
        legacy_config = self.config.model_dump_json(exclude={"renew_relay_certificate", "maintain_for_run"})
        state = dict(self.task_run.state[STATE_KEY])
        state["config_sha256"] = hashlib.sha256(legacy_config.encode()).hexdigest()
        state.pop("certificate_refresh_at")
        TaskRun.update_state_atomic(self.task_run.id, updates={STATE_KEY: state})
        self.clock.shift(10)
        self.controller().renew()
        self.assertEqual(self.registration().lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)

    def start_run_maintenance(self) -> FakeProbe:
        self.enterContext(
            patch("products.tasks.backend.logic.services.agent_egress_lifecycle.MAX_SANDBOX_TTL_SECONDS", 21600)
        )
        self.config = self.config.model_copy(update={"maintain_for_run": True, "renew_relay_certificate": True})
        sandbox = self.enroll_run()
        self.sandbox_expires_at = timezone.now().timestamp() + 1800
        return sandbox

    def test_run_maintenance_survives_multiple_certificate_and_capability_expiries(self) -> None:
        sandbox = self.start_run_maintenance()
        input = AgentEgressExecutionInput(
            probe=AgentEgressProbeInput(
                config_path="",
                team_id=self.team.id,
                run_id=str(self.task_run.id),
                sandbox_id=sandbox.id,
                enrollment=True,
                sandbox_expires_at=self.sandbox_expires_at,
            ),
            execution_id=str(self.execution_id),
            provisioning_deadline=timezone.now().timestamp() + 180,
        )
        with patch("products.tasks.backend.temporal.process_task.activities.agent_egress.activity.info") as info:
            info.return_value.workflow_run_id = "workflow-a"
            prepared = unwrap(_prepare)(input)
        self.assertEqual(prepared.enrollment_expires_at, self.sandbox_expires_at)
        probe = self.attached_relays[(sandbox.id, self.controller().relay_name)]
        registration = self.registration()
        for _ in range(75):
            self.clock.shift(20)
            self.controller().renew()
        self.assertEqual(len(probe.certificates), 4)
        self.assertEqual(len(probe.published), 9)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(self.registration().actor_epoch, registration.actor_epoch)
        self.assertEqual(self.registration().relay_key_sha256, registration.relay_key_sha256)
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["expires_at"], self.sandbox_expires_at)
        self.assertGreater(self.task_run.state[STATE_KEY]["certificate_expires_at"], timezone.now().timestamp())
        self.controller().close(reason="cancelled", sandbox_id=sandbox.id)
        self.assertTrue(self.registration().revoked)
        self.assertTrue(probe.destroyed)
        self.assertFalse(sandbox.destroyed)

    @parameterized.expand([("recovers",), ("expires",), ("revoked",)])
    def test_certificate_delivery_retry_preserves_only_live_authority(self, outcome: str) -> None:
        sandbox = self.start_run_maintenance()
        self.controller().prepare()
        probe = self.attached_relays[(sandbox.id, self.controller().relay_name)]
        self.task_run.refresh_from_db()
        deadline = self.task_run.state[STATE_KEY]["certificate_refresh_at"]

        def reject_delivery() -> None:
            if outcome == "revoked":
                self.controller().registry.revoke(
                    team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
                )
            raise AgentEgressCertificateDeliveryError("Reload not acknowledged")

        probe.on_certificate = reject_delivery
        for _ in range(44):
            self.clock.shift(10)
            self.controller().renew()
        self.clock.shift(10)
        if outcome == "revoked":
            with self.assertRaisesRegex(ValueError, "no longer has egress authority"):
                self.controller().renew()
            self.assertTrue(self.registration().revoked)
            return
        with capture_logs() as logs:
            self.controller().renew()
        self.assertEqual(logs[-1]["event"], "agent_egress_certificate_delivery_retry")
        for _ in range(9):
            self.clock.shift(10)
            self.controller().renew()
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["certificate_refresh_at"], deadline)
        self.assertEqual(len(probe.published), 4)
        self.assertEqual(len(probe.certificates), 1)
        if outcome == "recovers":
            probe.on_certificate = lambda: None
            self.clock.shift(10)
            self.controller().renew()
            self.assertEqual(len(probe.certificates), 2)
            self.task_run.refresh_from_db()
            self.assertGreater(self.task_run.state[STATE_KEY]["certificate_refresh_at"], deadline)
        else:
            for _ in range(35):
                self.clock.shift(10)
                self.controller().renew()
            expires_at = self.registration().lease_expires_at
            self.clock.shift(10)
            with self.assertRaisesRegex(ValueError, "certificate has expired"):
                self.controller().renew()
            self.assertEqual(self.registration().lease_expires_at, expires_at)

    @parameterized.expand([("csr",), ("acknowledgement",)])
    def test_certificate_expiry_during_delivery_ends_enrollment(self, phase: str) -> None:
        sandbox = self.start_run_maintenance()
        self.controller().prepare()
        probe = self.attached_relays[(sandbox.id, self.controller().relay_name)]

        def reject_delivery() -> None:
            raise AgentEgressCertificateDeliveryError("Retry later")

        probe.on_certificate = reject_delivery
        for _ in range(89):
            self.clock.shift(10)
            self.controller().renew()
        self.task_run.refresh_from_db()
        deadline = self.task_run.state[STATE_KEY]["certificate_expires_at"]
        probe.on_certificate = lambda: None

        def cross_expiry() -> None:
            self.clock.shift(6)

        if phase == "csr":
            probe.on_csr = cross_expiry
        else:
            probe.on_certificate = cross_expiry
        self.clock.shift(5)
        with self.assertRaisesRegex(ValueError, "certificate has expired"):
            self.controller().renew()
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["certificate_expires_at"], deadline)
        self.assertEqual(len(probe.certificates), 1 if phase == "csr" else 2)
        self.controller().close(reason="failed", sandbox_id=sandbox.id)
        self.assertTrue(self.registration().revoked)
        self.assertTrue(probe.destroyed)
        self.assertFalse(sandbox.destroyed)

    @parameterized.expand([("missing", None), ("expired", -1), ("nan", float("nan")), ("too_long", 21601)])
    def test_run_maintenance_rejects_invalid_sandbox_deadlines(self, _name: str, offset: float | None) -> None:
        self.start_run_maintenance()
        self.sandbox_expires_at = None if offset is None else timezone.now().timestamp() + offset
        with self.assertRaisesRegex(ValueError, "live sandbox deadline"):
            self.controller().prepare()
        self.assertEqual(self.attached_relays, {})
        self.assertFalse(AgentEgressRegistration.objects.for_team(self.team.id).exists())

    def test_retried_prepare_cannot_extend_the_sandbox_deadline(self) -> None:
        self.start_run_maintenance()
        self.controller().prepare()
        assert self.sandbox_expires_at is not None
        self.sandbox_expires_at += 60
        with self.assertRaisesRegex(ValueError, "sandbox deadline has changed"):
            self.controller().prepare()

    def test_run_maintenance_requires_certificate_renewal(self) -> None:
        self.config = self.config.model_copy(update={"maintain_for_run": True})
        with self.assertRaisesRegex(ValueError, "enrollment configuration"):
            self.enroll_run()

    def test_standalone_probe_cannot_enable_run_maintenance(self) -> None:
        self.config = self.config.model_copy(update={"maintain_for_run": True, "renew_relay_certificate": True})
        with self.assertRaisesRegex(ValueError, "requires enrollment configuration"):
            self.controller().prepare()

    @parameterized.expand([("disabled",), ("deleted",), ("changed",)])
    def test_enrollment_configuration_changes_stop_renewal_but_allow_cleanup(self, change: str) -> None:
        sandbox = self.enroll_run()
        controller = self.controller()
        self.assertEqual(controller.prepare(), sandbox.id)
        lease_expires_at = self.registration().lease_expires_at
        execution = AgentEgressExecutionInput(
            probe=AgentEgressProbeInput(
                config_path="",
                team_id=self.team.id,
                run_id=str(self.task_run.id),
                sandbox_id=sandbox.id,
                enrollment=True,
            ),
            execution_id=str(self.execution_id),
            provisioning_deadline=self.deadlines[self.execution_id],
        )
        path = self.config.client_ca_file.parent / "enrollment.json"
        if change == "disabled":
            self.enterContext(override_settings(AGENT_EGRESS_ENROLLMENT_CONFIG=""))
        elif change == "deleted":
            path.unlink()
        else:
            configuration = json.loads(path.read_text())
            configuration["endpoint_domain"] = "other.egress.example.com"
            path.write_text(json.dumps(configuration))
        self.clock.shift(10)
        with patch("products.tasks.backend.temporal.process_task.activities.agent_egress.activity.info") as info:
            info.return_value.workflow_run_id = "workflow-a"
            with self.assertRaises(ValueError):
                unwrap(renew_agent_egress)(execution)
            self.assertEqual(self.registration().lease_expires_at, lease_expires_at)
            unwrap(cleanup_agent_egress)(
                AgentEgressCleanupInput(execution=execution, sandbox_id=sandbox.id, reason="cancelled")
            )
        self.assertTrue(self.registration().revoked)
        self.assertTrue(self.attached_relays[(sandbox.id, controller.relay_name)].destroyed)
        self.assertFalse(sandbox.destroyed)
        self.task_run.refresh_from_db()
        self.assertTrue(self.task_run.state[STATE_KEY]["closed"])

    @parameterized.expand([("disabled", ""), ("replaced", "00000000-0000-0000-0000-000000000001")])
    def test_cleanup_survives_staging_opt_in_rotation(self, _name: str, selected_run: str) -> None:
        self.enterContext(
            override_settings(
                DEBUG=False,
                TEST=False,
                CLOUD_DEPLOYMENT="DEV",
                SANDBOX_PROVIDER="modal",
                AGENT_EGRESS_STAGING_PROBE_RUN_ID=str(self.task_run.id),
                AGENT_EGRESS_PROBE_CONFIG_DIR=str(self.config.client_ca_file.parent),
            )
        )
        sandbox_id = self.controller().prepare()
        config_path = self.config.client_ca_file.parent / "probe.json"
        config_path.write_text(self.config.model_dump_json())
        cleanup = AgentEgressCleanupInput(
            execution=AgentEgressExecutionInput(
                probe=AgentEgressProbeInput(
                    config_path=str(config_path), team_id=self.team.id, run_id=str(self.task_run.id)
                ),
                execution_id=str(self.execution_id),
            ),
            sandbox_id=sandbox_id,
            reason="cancelled",
        )
        with (
            override_settings(AGENT_EGRESS_STAGING_PROBE_RUN_ID=selected_run),
            patch("products.tasks.backend.temporal.process_task.activities.agent_egress.activity.info") as info,
        ):
            for operation in (self.controller().prepare, self.controller().renew, self.controller().probe):
                with self.assertRaises(ValueError):
                    operation()
            info.return_value.workflow_run_id = "workflow-b"
            with self.assertRaises(ValueError):
                unwrap(cleanup_agent_egress)(cleanup)
            self.assertFalse(self.registration().revoked)
            self.assertFalse(self.probes[sandbox_id].destroyed)
            info.return_value.workflow_run_id = "workflow-a"
            unwrap(cleanup_agent_egress)(cleanup)

        self.assertTrue(self.registration().revoked)
        self.assertTrue(self.probes[sandbox_id].destroyed)
        self.task_run.refresh_from_db()
        self.assertTrue(self.task_run.state[STATE_KEY]["closed"])

    @parameterized.expand(
        [("live", 401), ("cancel_requested", 401), ("cancelled", 503), ("completed", 503), ("failed", 503)]
    )
    def test_rejected_probe_preserves_failure_evidence(self, run_end: str, status: int) -> None:
        sandbox_id = self.controller().prepare()
        probe = self.probes[sandbox_id]
        probe.status = status

        def end_run() -> None:
            if run_end == "cancel_requested":
                TaskRun.update_state_atomic(
                    self.task_run.id, updates={"cancel_requested_at": timezone.now().isoformat()}
                )
            elif run_end != "live":
                TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=run_end)

        probe.on_probe = end_run
        with capture_logs() as logs:
            with self.assertRaises(ValueError) as error:
                self.controller().probe()
        self.assertEqual(isinstance(error.exception, AgentEgressRunEnded), run_end != "live")
        self.assertEqual(
            [log for log in logs if log["event"] == "agent_egress_probe_failed"],
            [
                {
                    "event": "agent_egress_probe_failed",
                    "log_level": "warning",
                    "team_id": self.team.id,
                    "run_id": str(self.task_run.id),
                    "execution_id": str(self.execution_id),
                    "statuses": {status: self.config.requests_per_round},
                }
            ],
        )

    @parameterized.expand([("completed",), ("create_response",), ("relay",), ("registration",), ("publication",)])
    def test_new_worker_recovers_enrollment_without_replacing_the_vm_or_key(self, failure: str) -> None:
        failed = False

        def fail_once() -> None:
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("Control plane unavailable")

        def registration_outage(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            if failure == "registration" and sql.startswith(f'INSERT INTO "{AgentEgressRegistration._meta.db_table}"'):
                fail_once()
            return execute(sql, params, many, context)

        if failure == "create_response":
            self.on_create = fail_once
        elif failure == "relay":
            self.on_start = fail_once
        elif failure == "publication":
            self.on_publish = fail_once
        with connection.execute_wrapper(registration_outage):
            if failure == "completed":
                self.controller().prepare()
            else:
                with self.assertRaisesRegex(OSError, "Control plane unavailable"):
                    self.controller().prepare()

        self.assertEqual(len(self.probes), 1)
        probe = next(iter(self.probes.values()))
        self.assertFalse(probe.destroyed)
        fingerprint = FakeIssuer(certificate=b"", private_key=b"").issue(probe.certificate_request()).relay_key_sha256
        self.task_run.refresh_from_db()
        expires_at = self.task_run.state[STATE_KEY]["expires_at"]
        self.clock.shift(1)
        sandbox_id = self.controller().prepare()
        self.assertEqual(sandbox_id, probe.id)
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(self.registration().relay_key_sha256, fingerprint)
        self.assertFalse(self.registration().revoked)
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["expires_at"], expires_at)

    @parameterized.expand([("expired",), ("revoked",)])
    def test_enrollment_retry_cannot_revive_lost_authority(self, failure: str) -> None:
        sandbox_id = self.controller().prepare()
        expiry = self.registration().lease_expires_at
        if failure == "expired":
            self.clock.shift(30)
        else:
            self.controller().registry.revoke(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        with self.assertRaises(ValueError):
            self.controller().prepare()
        self.assertEqual(self.registration().lease_expires_at, expiry)
        self.assertEqual(len(self.probes[sandbox_id].published), 1)
        self.assertEqual(len(self.probes), 1)

    @parameterized.expand([("standalone", False), ("attached", True)])
    def test_timed_out_prepare_cannot_close_a_successful_retry(self, _name: str, attached: bool) -> None:
        sandbox_id: str | None = None
        if attached:
            sandbox = FakeProbe()
            self.probes[sandbox.id] = sandbox
            TaskRun.update_state_atomic(
                self.task_run.id, updates={"sandbox_id": sandbox.id, "sandbox_backend": "modal"}
            )
            self.config = self.config.model_copy(update={"sandbox_id": sandbox.id})

        def complete_retry_before_resuming() -> None:
            nonlocal sandbox_id
            probe = next(iter(self.attached_relays.values() if attached else self.probes.values()))
            probe.on_start = lambda: None
            sandbox_id = self.controller().prepare()
            for _ in range(19):
                self.clock.shift(10)
                self.controller().renew()

        self.on_start = complete_retry_before_resuming
        with self.assertRaisesRegex(ValueError, "provisioning window"):
            self.controller().prepare()

        assert sandbox_id is not None
        relay = (
            self.attached_relays[(sandbox_id, self.controller().relay_name)] if attached else self.probes[sandbox_id]
        )
        self.assertEqual(len(self.probes), 1)
        self.assertFalse(self.probes[sandbox_id].destroyed)
        self.assertFalse(relay.destroyed)
        self.assertFalse(self.registration().revoked)
        self.assertEqual(self.registration().lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        self.task_run.refresh_from_db()
        self.assertFalse(self.task_run.state[STATE_KEY]["closed"])
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})

        self.controller().close(reason="completed", sandbox_id=sandbox_id)
        self.assertTrue(self.registration().revoked)
        self.assertTrue(relay.destroyed)
        self.assertEqual(self.probes[sandbox_id].destroyed, not attached)

    @parameterized.expand([("relay",), ("registration",)])
    def test_delayed_enrollment_cannot_publish_after_its_deadline(self, delay: str) -> None:
        def stall_registration(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: dict[str, object]
        ) -> object:
            result = execute(sql, params, many, context)
            if delay == "registration" and sql.startswith(f'INSERT INTO "{AgentEgressRegistration._meta.db_table}"'):
                self.clock.shift(181)
            return result

        if delay == "relay":
            self.on_start = lambda: self.clock.shift(181)
        with connection.execute_wrapper(stall_registration):
            with self.assertRaisesRegex(ValueError, "provisioning window"):
                self.controller().prepare()
        probe = next(iter(self.probes.values()))
        self.assertFalse(probe.published)
        self.controller().close(reason="failed", sandbox_id=probe.id)
        self.assertTrue(probe.destroyed)
        self.assertFalse(AgentEgressRegistration.objects.for_team(self.team.id).filter(revoked=False).exists())

    @parameterized.expand([("workflow",), ("execution",), ("team",), ("config",)])
    def test_other_owners_do_not_create_another_vm(self, mismatch: str) -> None:
        self.controller().prepare()
        config = self.config.model_copy(update={"team_id": self.other_team.id}) if mismatch == "team" else self.config
        if mismatch == "config":
            config = self.config.model_copy(update={"endpoint": "https://other.egress.example.com"})
        other = AgentEgressLifecycle(
            config,
            execution_id=uuid4() if mismatch == "execution" else self.execution_id,
            workflow_run_id="workflow-b" if mismatch == "workflow" else "workflow-a",
            provisioning_deadline=self.deadlines[self.execution_id],
        )
        expected = (
            TaskRun.DoesNotExist
            if mismatch == "team"
            else AgentEgressOwnershipConflict
            if mismatch == "execution"
            else ValueError
        )
        with self.assertRaises(expected):
            other.prepare()
        self.assertEqual(len(self.probes), 1)
        self.assertFalse(self.registration().revoked)

    @parameterized.expand([("lease_expires", False), ("provisioning_expires", True)])
    def test_enrollment_retry_waits_for_the_previous_lease(self, _name: str, missed_deadline: bool) -> None:
        self.config = self.config.model_copy(update={"maintain_for_run": True, "renew_relay_certificate": True})
        self.sandbox_expires_at = timezone.now().timestamp() + 900
        sandbox = self.enroll_run()
        self.controller().prepare()
        lease_expires_at = self.registration().lease_expires_at
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        with self.assertRaises(AgentEgressOwnershipConflict):
            replacement.prepare()
        execution = AgentEgressExecutionInput(
            probe=AgentEgressProbeInput(
                config_path="",
                team_id=self.team.id,
                run_id=str(self.task_run.id),
                sandbox_id=sandbox.id,
                enrollment=True,
                sandbox_expires_at=self.sandbox_expires_at,
            ),
            execution_id=str(replacement_id),
            provisioning_deadline=self.deadlines[replacement_id],
        )
        environment = ActivityEnvironment()
        environment.info = replace(environment.info, workflow_run_id="workflow-b")
        with self.assertRaises(ApplicationError) as raised:
            environment.run(unwrap(_prepare), execution)
        self.assertEqual(raised.exception.type, "AgentEgressOwnershipConflict")
        self.assertFalse(raised.exception.non_retryable)
        self.assertEqual(raised.exception.next_retry_delay, AGENT_EGRESS_LEASE_DURATION)
        self.assertIsInstance(raised.exception.__cause__, AgentEgressOwnershipConflict)
        self.assertEqual(self.registration().lease_expires_at, lease_expires_at)
        self.assertFalse(self.registration().revoked)
        self.assertEqual(len(self.attached_relays), 1)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.clock.shift(181 if missed_deadline else AGENT_EGRESS_LEASE_DURATION.total_seconds())
        if missed_deadline:
            with self.assertRaisesRegex(ValueError, "provisioning window"):
                environment.run(unwrap(_prepare), execution)
            self.assertEqual(len(self.attached_relays), 1)
            return
        prepared = environment.run(unwrap(_prepare), execution)
        self.assertEqual(prepared.sandbox_id, sandbox.id)
        self.assertEqual(prepared.enrollment_expires_at, self.sandbox_expires_at)
        replacement.renew()
        self.assertTrue(self.registration().revoked)
        self.assertFalse(self.registration(replacement_id).revoked)
        self.assertEqual(self.registration(replacement_id).actor_epoch, 2)
        self.assertTrue(self.attached_relays[(sandbox.id, self.controller().relay_name)].destroyed)
        self.assertFalse(self.attached_relays[(sandbox.id, replacement.relay_name)].destroyed)

    @parameterized.expand(
        [
            ("expired",),
            ("config",),
            ("workflow",),
            ("execution",),
            ("actor",),
            ("cancelled",),
            ("completed",),
            ("revoked",),
            ("missing",),
            ("sandbox",),
            ("closed",),
            ("probe_owner",),
        ]
    )
    def test_renewal_does_not_extend_invalid_authority(self, failure: str) -> None:
        self.controller().prepare()
        expires_at = self.registration().lease_expires_at
        self.clock.shift(30 if failure == "expired" else 10)
        config = (
            self.config.model_copy(update={"endpoint": "https://other.egress.example.com"})
            if failure == "config"
            else self.config
        )
        if failure == "actor":
            User.objects.filter(id=self.actor.id).update(is_active=False)
        elif failure == "revoked":
            self.controller().registry.revoke(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        elif failure == "missing":
            self.registration().delete()
        elif failure == "completed":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=TaskRun.Status.COMPLETED)
        elif failure == "cancelled":
            TaskRun.update_state_atomic(self.task_run.id, updates={"cancel_requested_at": timezone.now().isoformat()})
        elif failure in ("sandbox", "closed", "probe_owner"):
            self.task_run.refresh_from_db()
            probe = dict(self.task_run.state[STATE_KEY])
            probe.update(
                {"sandbox_id": "sb-foreign"}
                if failure == "sandbox"
                else {"closed": True}
                if failure == "closed"
                else {"owns_sandbox": False}
            )
            TaskRun.update_state_atomic(self.task_run.id, updates={STATE_KEY: probe})
        controller = AgentEgressLifecycle(
            config,
            execution_id=uuid4() if failure == "execution" else self.execution_id,
            workflow_run_id="workflow-b" if failure == "workflow" else "workflow-a",
        )
        with self.assertRaises(ValueError) as error:
            controller.renew()
        self.assertEqual(isinstance(error.exception, AgentEgressRunEnded), failure in ("cancelled", "completed"))
        if failure == "missing":
            self.assertIsNone(controller.registry.latest(team_id=self.team.id, run_id=self.task_run.id))
            return
        self.assertEqual(self.registration().lease_expires_at, expires_at)
        self.controller().close(reason="failed", sandbox_id=None)
        self.assertTrue(self.registration().revoked)
        with self.assertRaises(ValueError):
            self.controller().prepare()

    @parameterized.expand(
        [
            (status, operation)
            for status in ("completed", "cancelled", "failed", "cancel_requested")
            for operation in ("renew", "probe")
        ]
    )
    def test_activity_reports_run_end_without_extending_authority(self, status: str, operation: str) -> None:
        sandbox = self.enroll_run()
        self.controller().prepare()
        lease_expires_at = self.registration().lease_expires_at
        if status == "cancel_requested":
            TaskRun.update_state_atomic(self.task_run.id, updates={"cancel_requested_at": timezone.now().isoformat()})
        else:
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=status)
        execution = AgentEgressExecutionInput(
            probe=AgentEgressProbeInput(
                config_path="",
                team_id=self.team.id,
                run_id=str(self.task_run.id),
                sandbox_id=sandbox.id,
                enrollment=True,
            ),
            execution_id=str(self.execution_id),
        )
        with patch("products.tasks.backend.temporal.process_task.activities.agent_egress.activity.info") as info:
            info.return_value.workflow_run_id = "workflow-a"
            with self.assertRaises(ApplicationError) as error:
                unwrap(renew_agent_egress if operation == "renew" else _probe)(execution)
        self.assertEqual(error.exception.type, "AgentEgressRunEnded")
        self.assertEqual(list(error.exception.details), ["cancelled" if status == "cancel_requested" else status])
        self.assertTrue(error.exception.non_retryable)
        self.assertEqual(self.registration().lease_expires_at, lease_expires_at)
        self.assertIsNone(
            self.controller().registry.lookup(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        )

    def test_delayed_cleanup_leaves_the_replacement_live(self) -> None:
        previous = self.controller()
        previous_sandbox = previous.prepare()
        self.clock.shift(31)
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        replacement_sandbox = replacement.prepare()
        self.assertTrue(self.probes[previous_sandbox].destroyed)
        previous.close(reason="failed", sandbox_id=previous_sandbox)
        replacement.renew()
        self.assertTrue(self.probes[previous_sandbox].destroyed)
        self.assertFalse(self.probes[replacement_sandbox].destroyed)
        self.assertTrue(self.registration().revoked)
        self.assertFalse(self.registration(replacement_id).revoked)
        self.assertEqual(self.registration(replacement_id).actor_epoch, 2)
        self.assertNotEqual(self.registration().relay_key_sha256, self.registration(replacement_id).relay_key_sha256)
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["execution_id"], str(replacement_id))
        self.assertFalse(self.task_run.state[STATE_KEY]["closed"])

    def test_expired_cancellation_markers_are_pruned_without_allowing_old_enrollment(self) -> None:
        cancelled = self.controller()
        cancelled.close(reason="cancelled", sandbox_id=None)
        self.clock.shift(181)
        replacement = self.controller(execution_id=uuid4(), workflow_run_id="workflow-b")
        sandbox_id = replacement.prepare()
        replacement.close(reason="completed", sandbox_id=sandbox_id)
        cancelled.close(reason="cancelled", sandbox_id=None)
        self.task_run.refresh_from_db()
        self.assertNotIn(str(self.execution_id), self.task_run.state[STATE_KEY]["closed_executions"])
        with self.assertRaisesRegex(ValueError, "provisioning window"):
            cancelled.prepare()
        self.assertEqual(len(self.probes), 1)

    @parameterized.expand(
        [
            ("observation", False, False, False),
            ("enrollment", True, False, False),
            ("continued", True, True, False),
            ("rotated", True, True, True),
        ]
    )
    def test_attached_observation_owns_only_its_relay_during_replacement_and_cleanup(
        self, _name: str, enrollment: bool, maintain_for_run: bool, replace_sandbox: bool
    ) -> None:
        if maintain_for_run:
            self.config = self.config.model_copy(update={"maintain_for_run": True, "renew_relay_certificate": True})
            self.sandbox_expires_at = timezone.now().timestamp() + 900
        if enrollment:
            sandbox = self.enroll_run()
        else:
            sandbox = FakeProbe()
            self.probes[sandbox.id] = sandbox
            TaskRun.update_state_atomic(
                self.task_run.id, updates={"sandbox_id": sandbox.id, "sandbox_backend": "modal"}
            )
            self.config = self.config.model_copy(update={"sandbox_id": sandbox.id})
        previous = self.controller()
        self.assertEqual(previous.prepare(), sandbox.id)
        previous.renew()
        self.assertEqual(previous.probe(), {204: self.config.requests_per_round})
        previous_relay = self.attached_relays[(sandbox.id, previous.relay_name)]
        previous_capability = previous_relay.published[-1]
        if maintain_for_run:
            previous.close(reason="cancelled", sandbox_id=sandbox.id)
            self.clock.shift(1)
        else:
            self.clock.shift(31)
        replacement_sandbox = self.enroll_run() if replace_sandbox else sandbox
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        self.assertEqual(replacement.prepare(), replacement_sandbox.id)
        previous_revoked_at = self.registration().revoked_at
        self.clock.shift(1)
        previous.close(reason="failed", sandbox_id=sandbox.id)
        replacement_relay = self.attached_relays[(replacement_sandbox.id, replacement.relay_name)]
        self.assertTrue(previous_relay.destroyed)
        self.assertFalse(replacement_relay.destroyed)
        self.assertFalse(sandbox.destroyed)
        self.assertFalse(replacement_sandbox.destroyed)
        self.assertEqual(self.registration().revoked_at, previous_revoked_at)
        self.assertIsNotNone(previous_revoked_at)
        old_claims = jwt.decode(
            previous_capability, self.verification_key, algorithms=["RS256"], audience="posthog:agent_egress"
        )
        self.assertIsNone(
            previous.registry.lookup(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=UUID(old_claims["execution_id"])
            )
        )
        with self.assertRaises(ValueError):
            previous.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        replacement.renew()
        registration = replacement.registry.lookup(
            team_id=self.team.id, run_id=self.task_run.id, execution_id=replacement_id
        )
        self.assertIsNotNone(registration)
        assert registration is not None
        self.assertIsNone(registration.revoked_at)
        self.assertEqual(registration.actor_epoch, old_claims["actor_epoch"] + 1)
        self.assertNotEqual(registration.relay_key_sha256, old_claims["relay_key_sha256"])
        self.assertNotEqual(previous_capability, replacement_relay.published[-1])
        self.assertEqual(replacement.probe(), {204: self.config.requests_per_round})
        replacement.close(reason="completed", sandbox_id=replacement_sandbox.id)
        self.assertTrue(replacement_relay.destroyed)
        self.assertFalse(sandbox.destroyed)
        self.assertFalse(replacement_sandbox.destroyed)

    @parameterized.expand([("continued", False), ("rotated", True)])
    def test_failed_handoff_cannot_reopen_previous_execution(self, _name: str, replace_sandbox: bool) -> None:
        self.config = self.config.model_copy(update={"maintain_for_run": True, "renew_relay_certificate": True})
        self.sandbox_expires_at = timezone.now().timestamp() + 900
        sandbox = self.enroll_run()
        previous = self.controller()
        previous.prepare()
        previous.close(reason="cancelled", sandbox_id=sandbox.id)
        revoked_at = self.registration().revoked_at
        replacement_sandbox = self.enroll_run() if replace_sandbox else sandbox

        def refuse_publication() -> None:
            raise OSError("Provider unavailable")

        self.on_publish = refuse_publication
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        with self.assertRaisesRegex(OSError, "Provider unavailable"):
            replacement.prepare()
        replacement.close(reason="failed", sandbox_id=replacement_sandbox.id)
        with self.assertRaises(ValueError):
            previous.prepare()
        with self.assertRaises(ValueError):
            previous.renew()
        self.assertFalse(AgentEgressRegistration.objects.for_team(self.team.id).filter(revoked=False).exists())
        self.assertEqual(self.registration().revoked_at, revoked_at)
        self.assertEqual(self.registration().revocation_reason, "cancelled")
        self.assertTrue(all(relay.destroyed for relay in self.attached_relays.values()))
        self.assertFalse(sandbox.destroyed)
        self.assertFalse(replacement_sandbox.destroyed)

    @parameterized.expand([("sandbox",), ("backend",)])
    def test_observation_cannot_attach_to_a_foreign_sandbox(self, mismatch: str) -> None:
        sandbox = FakeProbe()
        self.probes[sandbox.id] = sandbox
        TaskRun.update_state_atomic(
            self.task_run.id,
            updates={
                "sandbox_id": "sb-other" if mismatch == "sandbox" else sandbox.id,
                "sandbox_backend": "hogland" if mismatch == "backend" else "modal",
            },
        )
        self.config = self.config.model_copy(update={"sandbox_id": sandbox.id})
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.controller().prepare()
        self.assertFalse(self.attached_relays)
        self.assertFalse(sandbox.destroyed)

    def test_legacy_input_cannot_start_an_unbounded_enrollment(self) -> None:
        controller = AgentEgressLifecycle(self.config, execution_id=self.execution_id, workflow_run_id="workflow-a")
        with self.assertRaisesRegex(ValueError, "provisioning window"):
            controller.prepare()
        self.assertFalse(self.probes)

    @parameterized.expand(
        [
            ("before_replacement", False, False),
            ("after_replacement", True, False),
            ("before_attached_replacement", False, True),
            ("after_attached_replacement", True, True),
        ]
    )
    def test_cleanup_before_claim_prevents_late_provisioning(
        self, _name: str, replacement_first: bool, enrollment: bool
    ) -> None:
        sandbox = self.enroll_run() if enrollment else None
        cancelled = self.controller()
        cancelled.close(reason="cancelled", sandbox_id=None)
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        if replacement_first:
            sandbox_id = replacement.prepare()
            replacement.close(reason="completed", sandbox_id=sandbox_id)

        with self.assertRaises(ValueError):
            cancelled.prepare()
        self.assertFalse(
            AgentEgressRegistration.objects.for_team(self.team.id).filter(execution_id=self.execution_id).exists()
        )
        self.assertEqual(len(self.probes), int(enrollment or replacement_first))

        if not replacement_first:
            replacement.prepare()
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(self.registration(replacement_id).revoked, replacement_first)
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["execution_id"], str(replacement_id))
        if sandbox is not None:
            self.assertFalse(sandbox.destroyed)

    def test_another_workflow_cannot_close_the_current_execution(self) -> None:
        sandbox_id = self.controller().prepare()
        with self.assertRaises(ValueError):
            self.controller(workflow_run_id="workflow-b").close(reason="failed", sandbox_id=sandbox_id)
        self.assertFalse(self.registration().revoked)
        self.assertFalse(self.probes[sandbox_id].destroyed)
        self.task_run.refresh_from_db()
        self.assertFalse(self.task_run.state[STATE_KEY]["closed"])

    @parameterized.expand(
        [(phase, failure) for phase in ("prepare", "refresh") for failure in ("write", "expired", "revoked", "slow")]
    )
    def test_capability_publication_failure_is_closed_by_cleanup(self, phase: str, failure: str) -> None:
        def fail_delivery() -> None:
            if failure == "write":
                raise OSError("Provider write failed")
            self.clock.shift(31 if failure == "expired" else 21)
            if failure == "revoked":
                self.controller().registry.revoke(
                    team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
                )

        controller = self.controller()
        sandbox_id = None
        if phase == "prepare":
            self.on_publish = fail_delivery
        else:
            sandbox_id = controller.prepare()
            for _ in range(17):
                self.clock.shift(10)
                self.controller().renew()
            self.clock.shift(10)
            self.probes[sandbox_id].on_publish = fail_delivery
        if failure == "slow":
            controller.prepare() if phase == "prepare" else self.controller().renew()
            self.assertEqual(self.registration().lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
            self.clock.shift(10)
            self.controller().renew()
        else:
            with self.assertRaises(OSError if failure == "write" else ValueError):
                controller.prepare() if phase == "prepare" else self.controller().renew()
        self.controller().close(reason="failed", sandbox_id=sandbox_id)
        self.assertTrue(self.registration().revoked)
        self.assertEqual(self.registration().revoked_by, "unknown" if failure == "revoked" else "egress-probe")
        self.assertTrue(all(probe.destroyed for probe in self.probes.values()))
        self.task_run.refresh_from_db()
        self.assertTrue(self.task_run.state[STATE_KEY]["closed"])

    @parameterized.expand([("run",), ("state",), ("unsaved",)])
    def test_cleanup_destroys_the_vm_when_run_state_is_gone(self, missing: str) -> None:
        controller = self.controller()
        if missing == "unsaved":

            def fail_creation_response() -> None:
                raise OSError("Worker disconnected")

            self.on_create = fail_creation_response
            with self.assertRaises(OSError):
                controller.prepare()
            sandbox_id = next(iter(self.probes))
        else:
            sandbox_id = controller.prepare()
        runs = TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id)
        if missing == "run":
            runs.delete()
        elif missing == "state":
            runs.update(state={})
        controller.close(reason="cancelled", sandbox_id=None if missing == "unsaved" else sandbox_id)
        self.assertTrue(self.probes[sandbox_id].destroyed)

    @parameterized.expand([("missing",), ("unavailable",)])
    def test_cleanup_distinguishes_a_missing_vm_from_a_provider_outage(self, failure: str) -> None:
        sandbox_id = self.controller().prepare()
        self.probes[sandbox_id].destroy()
        if failure == "missing":
            self.controller().close(reason="completed", sandbox_id=sandbox_id)
            self.controller().close(reason="completed", sandbox_id=sandbox_id)
        else:
            with patch.object(ModalEgressProbe, "close_sandbox", side_effect=OSError("Provider unavailable")):
                with self.assertRaisesRegex(OSError, "Provider unavailable"):
                    self.controller().close(reason="failed", sandbox_id=sandbox_id)
        self.assertTrue(self.registration().revoked)
        self.task_run.refresh_from_db()
        self.assertTrue(self.task_run.state[STATE_KEY]["closed"])

    def test_runner_preserves_terminal_error_when_cleanup_also_fails(self) -> None:
        def fail_delivery() -> None:
            raise ValueError("Provider rejected delivery")

        self.on_publish = fail_delivery
        with patch.object(ModalEgressProbe, "close_sandbox", side_effect=OSError("Provider unavailable")):
            with self.assertRaisesRegex(ValueError, "Provider rejected delivery"):
                AgentEgressProbeRunner(self.config, report=lambda result: None).run()
        registration = AgentEgressRegistration.objects.for_team(self.team.id).get(task_run_id=self.task_run.id)
        self.assertTrue(registration.revoked)
        self.task_run.refresh_from_db()
        self.assertTrue(self.task_run.state[STATE_KEY]["closed"])
        state = self.task_run.state[STATE_KEY]
        sandbox_id = state["sandbox_id"]
        self.controller(execution_id=UUID(state["execution_id"]), workflow_run_id=state["workflow_run_id"]).close(
            reason="failed", sandbox_id=None
        )
        self.assertTrue(self.probes[sandbox_id].destroyed)

    def test_cleanup_of_an_unstarted_execution_preserves_the_active_execution(self) -> None:
        sandbox_id = self.controller().prepare()
        abandoned = self.controller(execution_id=uuid4(), workflow_run_id="workflow-b")
        abandoned.close(reason="cancelled", sandbox_id=None)
        with self.assertRaises(ValueError):
            abandoned.prepare()
        self.assertFalse(self.registration().revoked)
        self.assertFalse(self.probes[sandbox_id].destroyed)
        self.controller().renew()
