from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
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

from posthog.models import Organization, OrganizationMembership, Team, User

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION
from products.tasks.backend.logic.services.agent_egress_lifecycle import STATE_KEY, AgentEgressLifecycle
from products.tasks.backend.logic.services.agent_egress_probe import AgentEgressProbeCertificate, AgentEgressProbeConfig
from products.tasks.backend.logic.services.agent_egress_probe_runner import AgentEgressProbeRunner
from products.tasks.backend.logic.services.connection_token import reset_sandbox_jwt_key_cache
from products.tasks.backend.logic.services.modal_egress_probe import ModalEgressProbe
from products.tasks.backend.models import AgentEgressRegistration, Task, TaskRun


class FakeIssuer:
    def __init__(self, *, certificate: bytes, private_key: bytes) -> None:
        pass

    def issue(self, csr: str) -> AgentEgressProbeCertificate:
        return AgentEgressProbeCertificate(
            certificate=f"signed:{csr}",
            relay_key_sha256=base64.urlsafe_b64encode(hashlib.sha256(csr.encode()).digest()).decode().rstrip("="),
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

    def certificate_request(self) -> str:
        return self.object_id

    def start_relay(self, *, certificate: str, server_ca: str) -> None:
        self.on_start()

    def publish_capability(self, capability: str) -> None:
        self.published.append(capability)
        self.on_publish()

    def probe(self, *, count: int, concurrency: int) -> dict[int, int]:
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
        )

    def registration(self, execution_id: UUID | None = None) -> AgentEgressRegistration:
        return AgentEgressRegistration.objects.for_team(self.team.id).get(
            execution_id=execution_id or self.execution_id
        )

    def test_new_worker_renews_and_refreshes_the_existing_execution(self) -> None:
        TaskRun.update_state_atomic(self.task_run.id, updates={"unrelated": "preserved"})
        sandbox_id = self.controller().prepare()
        for _ in range(18):
            self.clock.shift(10)
            self.controller().renew()
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(AgentEgressRegistration.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(self.registration().lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        self.assertEqual(len(self.probes[sandbox_id].published), 2)
        claims = jwt.decode(
            self.probes[sandbox_id].published[-1],
            self.verification_key,
            algorithms=["RS256"],
            audience="posthog:agent_egress",
        )
        self.assertEqual(claims["execution_id"], str(self.execution_id))
        self.assertEqual(claims["actor_id"], self.actor.id)
        self.assertEqual(claims["relay_key_sha256"], self.registration().relay_key_sha256)
        self.assertEqual(claims["actor_epoch"], self.registration().actor_epoch)
        self.assertEqual(claims["exp"], int(timezone.now().timestamp()) + 300)
        self.assertNotEqual(self.probes[sandbox_id].published[0], self.probes[sandbox_id].published[-1])
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state["unrelated"], "preserved")
        self.assertEqual(self.task_run.state[STATE_KEY]["sandbox_id"], sandbox_id)
        self.assertEqual(self.controller().probe(), {204: self.config.requests_per_round})

    def test_rejected_probe_raises_a_non_retryable_error(self) -> None:
        sandbox_id = self.controller().prepare()
        self.probes[sandbox_id].status = 401
        with self.assertRaises(ValueError):
            self.controller().probe()

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
        with self.assertRaises(TaskRun.DoesNotExist if mismatch == "team" else ValueError):
            other.prepare()
        self.assertEqual(len(self.probes), 1)
        self.assertFalse(self.registration().revoked)

    @parameterized.expand(
        [
            ("expired",),
            ("config",),
            ("workflow",),
            ("execution",),
            ("actor",),
            ("cancelled",),
            ("completed",),
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
        with self.assertRaises(ValueError):
            controller.renew()
        self.assertEqual(self.registration().lease_expires_at, expires_at)
        self.controller().close(reason="failed", sandbox_id=None)
        self.assertTrue(self.registration().revoked)
        with self.assertRaises(ValueError):
            self.controller().prepare()

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

    def test_attached_observation_owns_only_its_relay_during_replacement_and_cleanup(self) -> None:
        sandbox = FakeProbe()
        self.probes[sandbox.id] = sandbox
        TaskRun.update_state_atomic(self.task_run.id, updates={"sandbox_id": sandbox.id, "sandbox_backend": "modal"})
        self.config = self.config.model_copy(update={"sandbox_id": sandbox.id})
        previous = self.controller()
        self.assertEqual(previous.prepare(), sandbox.id)
        previous.renew()
        self.assertEqual(previous.probe(), {204: self.config.requests_per_round})
        self.clock.shift(31)
        replacement_id = uuid4()
        replacement = self.controller(execution_id=replacement_id, workflow_run_id="workflow-b")
        self.assertEqual(replacement.prepare(), sandbox.id)
        previous.close(reason="failed", sandbox_id=sandbox.id)
        self.assertTrue(self.attached_relays[(sandbox.id, previous.relay_name)].destroyed)
        self.assertFalse(self.attached_relays[(sandbox.id, replacement.relay_name)].destroyed)
        self.assertFalse(sandbox.destroyed)
        replacement.renew()
        self.assertFalse(self.registration(replacement_id).revoked)
        replacement.close(reason="completed", sandbox_id=sandbox.id)
        self.assertTrue(self.attached_relays[(sandbox.id, replacement.relay_name)].destroyed)
        self.assertFalse(sandbox.destroyed)

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

    @parameterized.expand([("before_replacement", False), ("after_replacement", True)])
    def test_cleanup_before_claim_prevents_late_provisioning(self, _name: str, replacement_first: bool) -> None:
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
        self.assertEqual(len(self.probes), int(replacement_first))

        if not replacement_first:
            replacement.prepare()
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(self.registration(replacement_id).revoked, replacement_first)
        self.task_run.refresh_from_db()
        self.assertEqual(self.task_run.state[STATE_KEY]["execution_id"], str(replacement_id))

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
