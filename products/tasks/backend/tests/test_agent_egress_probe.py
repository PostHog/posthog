import base64
import hashlib
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

import time_machine
from unittest.mock import PropertyMock, patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.user_permissions import UserPermissions

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION, AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_probe import (
    AgentEgressProbeSession,
    AgentEgressProbeStoppedError,
)
from products.tasks.backend.logic.services.agent_egress_probe_runner import (
    AgentEgressProbeConfig,
    AgentEgressProbeIssuer,
    AgentEgressProbeRunner,
)
from products.tasks.backend.logic.services.connection_token import reset_sandbox_jwt_key_cache
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.models import AgentEgressRegistration, Task, TaskRun


def probe_config(*, team_id: int = 1, run_id: UUID | None = None) -> AgentEgressProbeConfig:
    return AgentEgressProbeConfig(
        team_id=team_id,
        run_id=run_id or uuid4(),
        endpoint="https://run-a.egress.example.com",
        relay_image_id="im-synthetic-relay",
        server_ca_file=Path("/unused/server-ca.pem"),
        client_ca_file=Path("/unused/client-ca.pem"),
        client_ca_key_file=Path("/unused/client-ca-key.pem"),
    )


class TestAgentEgressProbeValidation(SimpleTestCase):
    @parameterized.expand([(False, "MODAL_DOCKER"), (True, "MODAL"), (True, "DOCKER")])
    def test_runner_rejects_non_development_provider_before_database_or_cloud_access(
        self, debug: bool, provider: str
    ) -> None:
        with (
            override_settings(DEBUG=debug, SANDBOX_PROVIDER=provider),
            patch.object(ModalEgressProbe, "create") as create,
        ):
            with self.assertRaisesRegex(ValueError, "require DEBUG"):
                AgentEgressProbeRunner(probe_config(), report=lambda event: None).run()
        create.assert_not_called()

    def test_issuer_ignores_requested_authority_and_binds_the_signed_relay_key(self) -> None:
        with time_machine.travel("2026-11-16T12:00:00Z", tick=False):
            now = timezone.now()
            ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic probe issuer")])
            ca = (
                x509.CertificateBuilder()
                .subject_name(ca_name)
                .issuer_name(ca_name)
                .public_key(ca_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1))
                .not_valid_after(now + timedelta(minutes=10))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .sign(ca_key, hashes.SHA256())
            )
            relay_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            csr = (
                x509.CertificateSigningRequestBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic relay")]))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("admin.example.com")]), critical=False)
                .sign(relay_key, hashes.SHA256())
            )
            issuer = AgentEgressProbeIssuer(
                certificate=ca.public_bytes(serialization.Encoding.PEM),
                private_key=ca_key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                ),
            )
            issued = issuer.issue(csr.public_bytes(serialization.Encoding.PEM).decode())
            leaf = x509.load_pem_x509_certificate(issued.certificate.encode())
            leaf.verify_directly_issued_by(ca)
            self.assertFalse(leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
            self.assertEqual(
                list(leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value),
                [ExtendedKeyUsageOID.CLIENT_AUTH],
            )
            with self.assertRaises(x509.ExtensionNotFound):
                leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            self.assertEqual(leaf.not_valid_after_utc, ca.not_valid_after_utc)
            spki = relay_key.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            self.assertEqual(
                issued.relay_key_sha256,
                base64.urlsafe_b64encode(hashlib.sha256(spki).digest()).decode().rstrip("="),
            )
            self.assertEqual(
                leaf.public_key().public_bytes(
                    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
                ),
                spki,
            )


class TestAgentEgressProbeSession(TestCase):
    team: ClassVar[Team]
    actor: ClassVar[User]
    task_run: ClassVar[TaskRun]
    signing_key: ClassVar[str]
    verification_key: ClassVar[str]

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Egress probe tests")
        cls.team = Team.objects.create(organization=organization, name="Egress")
        cls.actor = User.objects.create(email="probe@example.com")
        OrganizationMembership.objects.create(organization=organization, user=cls.actor)
        task = Task.objects.create(team=cls.team, created_by=cls.actor, title="Synthetic probe")
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
        travel = time_machine.travel("2026-11-16T12:00:00Z", tick=False)
        self.clock = travel.start()
        self.addCleanup(travel.stop)
        self.enterContext(
            override_settings(SANDBOX_JWT_PRIVATE_KEY=self.signing_key, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None)
        )
        reset_sandbox_jwt_key_cache()
        self.addCleanup(reset_sandbox_jwt_key_cache)
        self.elapsed = 0.0
        self.published: list[str] = []
        self.registry = AgentEgressRegistry(region="test-us")
        self.session = self.new_session("first")

    def new_session(
        self, relay: str, *, publish_capability: Callable[[str], None] | None = None
    ) -> AgentEgressProbeSession:
        return AgentEgressProbeSession(
            registry=self.registry,
            team_id=self.team.id,
            run_id=self.task_run.id,
            actor_id=self.actor.id,
            authority="run-a.egress.example.com",
            relay_key_sha256=base64.urlsafe_b64encode(hashlib.sha256(relay.encode()).digest()).decode().rstrip("="),
            publish_capability=publish_capability or self.published.append,
            monotonic=lambda: self.elapsed,
        )

    def advance(self, seconds: int) -> None:
        self.elapsed += seconds
        self.clock.shift(timedelta(seconds=seconds))

    def registration(self, session: AgentEgressProbeSession) -> AgentEgressRegistration:
        return AgentEgressRegistration.objects.for_team(self.team.id).get(execution_id=session.execution_id)

    def test_renewal_keeps_the_guest_capability_live_then_stop_revokes_it(self) -> None:
        started = self.session.start()
        initial_capability = self.published[0]
        for _ in range(17):
            self.advance(10)
            self.session.tick()
        self.assertEqual(self.published, [initial_capability])
        self.advance(10)
        renewed = self.session.tick()
        self.assertEqual(len(self.published), 2)
        self.assertEqual(renewed.execution_id, started.execution_id)
        self.assertEqual(renewed.lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        claims = jwt.decode(
            self.published[-1],
            self.verification_key,
            algorithms=["RS256"],
            issuer="posthog:tasks",
            audience="posthog:agent_egress",
        )
        self.assertEqual(claims["execution_id"], str(started.execution_id))
        self.assertEqual(claims["relay_key_sha256"], self.session.relay_key_sha256)
        self.assertEqual(claims["actor_epoch"], started.actor_epoch)
        self.assertEqual(claims["exp"], int(timezone.now().timestamp()) + 300)
        self.assertNotEqual(initial_capability, self.published[-1])

        self.session.stop()
        self.session.stop()
        self.assertTrue(self.registration(self.session).revoked)
        with self.assertRaises(AgentEgressProbeStoppedError):
            self.session.tick()

    @parameterized.expand([("cancel",), ("completed",), ("actor",), ("expired",)])
    def test_lost_authority_stops_the_session_permanently(self, reason: str) -> None:
        self.session.start()
        if reason == "cancel":
            TaskRun.update_state_atomic(self.task_run.id, updates={"cancel_requested_at": timezone.now().isoformat()})
        elif reason == "completed":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=TaskRun.Status.COMPLETED)
        elif reason == "actor":
            User.objects.filter(id=self.actor.id).update(is_active=False)
        else:
            self.advance(31)

        with self.assertRaises(AgentEgressProbeStoppedError):
            self.session.tick()
        self.assertTrue(self.registration(self.session).revoked)
        with self.assertRaises(AgentEgressProbeStoppedError):
            self.session.start()
        self.assertEqual(len(self.published), 1)

    @parameterized.expand([("start",), ("refresh",)])
    def test_failed_capability_delivery_revokes_even_after_a_partial_write(self, phase: str) -> None:
        should_fail = phase == "start"

        def publish(capability: str) -> None:
            self.published.append(capability)
            if should_fail:
                raise OSError("Provider write failed")

        session = self.new_session("publisher", publish_capability=publish)
        if phase == "refresh":
            session.start()
            for _ in range(17):
                self.advance(10)
                session.tick()
            self.advance(10)
            should_fail = True
        with self.assertRaisesRegex(OSError, "Provider write failed"):
            session.start() if phase == "start" else session.tick()
        self.assertTrue(self.registration(session).revoked)
        self.assertIsNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=session.execution_id)
        )
        with self.assertRaises(AgentEgressProbeStoppedError):
            session.tick()

    @parameterized.expand(
        [(phase, result) for phase in ("start", "refresh") for result in ("slow", "expired", "revoked")]
    )
    def test_capability_delivery_rechecks_authority_before_returning(self, phase: str, result: str) -> None:
        exercise_delivery = phase == "start"

        def publish(capability: str) -> None:
            self.published.append(capability)
            if exercise_delivery:
                self.advance(30 if result == "expired" else 21)
                if result == "revoked":
                    self.registry.revoke(
                        team_id=self.team.id, run_id=self.task_run.id, execution_id=session.execution_id
                    )

        session = self.new_session("publisher", publish_capability=publish)
        if phase == "refresh":
            session.start()
            for _ in range(17):
                self.advance(10)
                session.tick()
            self.advance(10)
            exercise_delivery = True
        deliver = session.start if phase == "start" else session.tick
        if result == "slow":
            registration = deliver()
            self.assertEqual(registration.lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
            self.advance(10)
            self.assertEqual(session.tick().execution_id, registration.execution_id)
        else:
            with self.assertRaises(AgentEgressProbeStoppedError):
                deliver()
            self.assertTrue(self.registration(session).revoked)
            self.assertIsNone(
                self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=session.execution_id)
            )
            with self.assertRaises(AgentEgressProbeStoppedError):
                session.tick()

    def test_registry_failure_stops_renewal_and_preserves_the_original_error(self) -> None:
        self.session.start()
        with (
            patch.object(
                UserPermissions, "current_team", new_callable=PropertyMock, side_effect=OperationalError("read")
            ),
            patch.object(self.registry, "revoke", side_effect=OperationalError("revoke")),
        ):
            with self.assertRaisesRegex(OperationalError, "read"):
                self.session.tick()
        with self.assertRaises(AgentEgressProbeStoppedError):
            self.session.tick()
        self.session.stop()
        self.assertTrue(self.registration(self.session).revoked)

    def test_replacement_recovers_expired_execution_and_stale_stop_cannot_revoke_it(self) -> None:
        original = self.session.start()
        self.advance(31)
        replacement = self.new_session("replacement")
        current = replacement.start()
        self.session.stop()

        self.assertTrue(self.registration(self.session).revoked)
        self.assertEqual(current.actor_epoch, original.actor_epoch + 1)
        self.assertNotEqual(current.relay_key_sha256, original.relay_key_sha256)
        self.assertEqual(replacement.tick().execution_id, current.execution_id)
        self.assertFalse(self.registration(replacement).revoked)

    def test_stop_before_enrollment_does_not_revoke_an_existing_execution(self) -> None:
        self.session.start()
        abandoned = self.new_session("abandoned")
        abandoned.stop()
        with self.assertRaises(AgentEgressProbeStoppedError):
            abandoned.start()
        self.assertFalse(self.registration(self.session).revoked)

    @parameterized.expand(
        [("cancelled",), ("terminal",), ("local",), ("sandbox",), ("repository",), ("repositories",), ("environment",)]
    )
    @override_settings(DEBUG=True, SANDBOX_PROVIDER="MODAL_DOCKER")
    def test_runner_rejects_ineligible_runs_before_provisioning(self, reason: str) -> None:
        if reason == "terminal":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=TaskRun.Status.COMPLETED)
        elif reason == "local":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(
                environment=TaskRun.Environment.LOCAL
            )
        elif reason in ("repository", "repositories"):
            task = self.task_run.task
            task.repository = "example/probe" if reason == "repository" else None
            task.repositories = ["example/probe"] if reason == "repositories" else []
            task.save(update_fields=["repository", "repositories"])
        else:
            key = {
                "cancelled": "cancel_requested_at",
                "sandbox": "sandbox_id",
                "environment": "sandbox_environment_id",
            }[reason]
            TaskRun.update_state_atomic(self.task_run.id, updates={key: "synthetic-existing-value"})
        with patch.object(ModalEgressProbe, "create") as create:
            with self.assertRaisesRegex(ValueError, "Use an active development run"):
                AgentEgressProbeRunner(
                    probe_config(team_id=self.team.id, run_id=self.task_run.id), report=lambda event: None
                ).run()
        create.assert_not_called()
