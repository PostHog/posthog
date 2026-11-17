import base64
import signal
import asyncio
import hashlib
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from uuid import UUID, uuid4

import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from parameterized import parameterized
from temporalio.api.failure.v1 import Failure
from temporalio.converter import DefaultFailureConverter, DefaultPayloadConverter

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeConfig, AgentEgressProbeIssuer
from products.tasks.backend.logic.services.agent_egress_probe_runner import AgentEgressProbeRunner
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.agent_egress import (
    AgentEgressExecutionInput,
    AgentEgressProbeInput,
    lifecycle,
)


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
    @parameterized.expand([(False, "MODAL_DOCKER", "/unused"), (True, "DOCKER", "/unused"), (True, "MODAL_DOCKER", "")])
    def test_worker_rejects_unconfigured_probes_before_reading_files(
        self, debug: bool, provider: str, directory: str
    ) -> None:
        input = AgentEgressExecutionInput(
            probe=AgentEgressProbeInput(config_path="/unused/probe.json", team_id=1, run_id=str(uuid4())),
            execution_id=str(uuid4()),
        )
        with (
            override_settings(DEBUG=debug, SANDBOX_PROVIDER=provider, AGENT_EGRESS_PROBE_CONFIG_DIR=directory),
            patch.object(Path, "read_bytes", side_effect=AssertionError("File access is disabled")),
        ):
            with self.assertRaisesRegex(ValueError, "require DEBUG|Set AGENT_EGRESS_PROBE_CONFIG_DIR"):
                lifecycle(input)

    @parameterized.expand([("allowed",), ("outside",), ("traversal",), ("symlink",)])
    @override_settings(DEBUG=True, SANDBOX_PROVIDER="MODAL_DOCKER")
    def test_configuration_reads_stay_in_the_configured_directory(self, location: str) -> None:
        with TemporaryDirectory() as temporary:
            directory = Path(temporary) / "configs"
            directory.mkdir()
            outside = Path(temporary) / "configs-other"
            outside.mkdir()
            config = probe_config()
            path = directory / "probe.json"
            path.write_text(config.model_dump_json())
            other = outside / "probe.json"
            other.write_text(config.model_dump_json())
            if location == "outside":
                path = other
            elif location == "traversal":
                path = directory / ".." / "configs-other" / "probe.json"
            elif location == "symlink":
                path = directory / "linked.json"
                path.symlink_to(other)
            with override_settings(AGENT_EGRESS_PROBE_CONFIG_DIR=str(directory)):
                if location == "allowed":
                    self.assertEqual(AgentEgressProbeConfig.load(path), config)
                else:
                    with self.assertRaisesRegex(ValueError, "Invalid egress probe configuration"):
                        AgentEgressProbeConfig.load(path)

    @parameterized.expand([("json",), ("fields",), ("missing",)])
    @override_settings(DEBUG=True, SANDBOX_PROVIDER="MODAL_DOCKER")
    def test_configuration_errors_do_not_disclose_content_in_activity_failures(self, invalid: str) -> None:
        marker = "synthetic-private-config-value"
        with TemporaryDirectory() as directory, override_settings(AGENT_EGRESS_PROBE_CONFIG_DIR=directory):
            path = Path(directory) / f"{marker}.json"
            if invalid != "missing":
                path.write_text(marker if invalid == "json" else '{"unexpected":"' + marker + '"}')
            with self.assertRaisesRegex(ValueError, "^Invalid egress probe configuration$") as error:
                AgentEgressProbeConfig.load(path)
            failure = Failure()
            DefaultFailureConverter().to_failure(error.exception, DefaultPayloadConverter(), failure)
            self.assertNotIn(marker.encode(), failure.SerializeToString())

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


class TestAgentEgressProbeCommand(TestCase):
    team: ClassVar[Team]
    actor: ClassVar[User]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Egress probe tests")
        cls.team = Team.objects.create(organization=organization, name="Egress")
        cls.actor = User.objects.create(email="probe@example.com")
        OrganizationMembership.objects.create(organization=organization, user=cls.actor)
        task = Task.objects.create(team=cls.team, created_by=cls.actor, title="Synthetic probe")
        cls.task_run = TaskRun.objects.create(team=cls.team, task=task, status=TaskRun.Status.IN_PROGRESS)

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

    @override_settings(DEBUG=True, SANDBOX_PROVIDER="MODAL_DOCKER")
    def test_temporal_command_interrupt_cancels_the_remote_workflow(self) -> None:
        async def interrupt() -> dict[int, int]:
            signal.raise_signal(signal.SIGINT)
            await asyncio.sleep(0)
            return {}

        handle = MagicMock(id="egress-test", first_execution_run_id="workflow-test")
        handle.result = AsyncMock(side_effect=interrupt)
        handle.cancel = AsyncMock()
        client = MagicMock(start_workflow=AsyncMock(return_value=handle))
        previous_handler = signal.signal(signal.SIGINT, signal.default_int_handler)
        try:
            with (
                TemporaryDirectory() as directory,
                override_settings(AGENT_EGRESS_PROBE_CONFIG_DIR=directory),
                patch(
                    "products.tasks.backend.management.commands.probe_agent_egress.async_connect",
                    new=AsyncMock(return_value=client),
                ),
            ):
                path = Path(directory) / "probe.json"
                path.write_text(probe_config(team_id=self.team.id, run_id=self.task_run.id).model_dump_json())
                with self.assertRaises(KeyboardInterrupt):
                    call_command(
                        "probe_agent_egress",
                        "--config",
                        str(path),
                        "--temporal",
                        "--task-queue",
                        "egress-test",
                        stdout=StringIO(),
                    )
            handle.cancel.assert_awaited_once()
        finally:
            signal.signal(signal.SIGINT, previous_handler)
