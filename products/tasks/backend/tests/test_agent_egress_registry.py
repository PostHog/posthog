from datetime import timedelta
from typing import ClassVar
from uuid import UUID, uuid4

import time_machine
from unittest.mock import PropertyMock, patch

from django.db import OperationalError, connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.user_permissions import UserPermissions

from products.tasks.backend.logic.services.agent_egress import AGENT_EGRESS_LEASE_DURATION, AgentEgressRegistry
from products.tasks.backend.logic.services.connection_token import (
    SANDBOX_JWT_STATE_KID_KEY,
    get_primary_sandbox_jwt_kid,
    reset_sandbox_jwt_key_cache,
)
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, AgentEgressRegistration, Task, TaskRun


class TestAgentEgressRegistry(TestCase):
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    actor: ClassVar[User]
    other_actor: ClassVar[User]
    task_run: ClassVar[TaskRun]

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Egress registry tests")
        cls.team = Team.objects.create(organization=organization, name="Egress")
        cls.other_team = Team.objects.create(organization=organization, name="Other")
        cls.actor = User.objects.create(email="egress@example.com")
        cls.other_actor = User.objects.create(email="other-egress@example.com")
        OrganizationMembership.objects.create(organization=organization, user=cls.actor)
        OrganizationMembership.objects.create(organization=organization, user=cls.other_actor)
        task = Task.objects.create(team=cls.team, created_by=cls.actor, title="Synthetic operation")
        cls.task_run = TaskRun.objects.create(team=cls.team, task=task, status=TaskRun.Status.IN_PROGRESS)

    def setUp(self) -> None:
        self.travel = time_machine.travel("2026-11-12T12:00:00Z", tick=False)
        self.clock = self.travel.start()
        self.addCleanup(self.travel.stop)
        self.registry = AgentEgressRegistry(region="test-us")
        self.execution_id = uuid4()

    def register(
        self,
        *,
        execution_id: UUID | None = None,
        previous_execution_id: UUID | None = None,
        actor_id: int | None = None,
        authority: str = "run-a.egress.example.com",
        relay_key_sha256: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    ) -> AgentEgressRegistration:
        return self.registry.register(
            team_id=self.team.id,
            run_id=self.task_run.id,
            execution_id=execution_id or self.execution_id,
            previous_execution_id=previous_execution_id,
            actor_id=actor_id if actor_id is not None else self.actor.id,
            authority=authority,
            relay_key_sha256=relay_key_sha256,
        )

    def test_only_renewal_extends_a_live_lease(self) -> None:
        self.assertIsNone(self.registry.latest(team_id=self.team.id, run_id=self.task_run.id))
        registration = self.register()
        self.assertEqual(registration.lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        self.clock.shift(timedelta(seconds=20))

        repeated = self.register()
        looked_up = self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        self.assertIsNotNone(looked_up)
        assert looked_up is not None
        self.assertEqual(repeated.lease_expires_at, registration.lease_expires_at)
        self.assertEqual(repeated.actor_epoch, registration.actor_epoch)
        self.assertEqual(looked_up.lease_expires_at, registration.lease_expires_at)

        renewed = self.registry.renew(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        assert renewed is not None
        self.assertEqual(renewed.lease_expires_at, timezone.now() + AGENT_EGRESS_LEASE_DURATION)
        self.clock.shift(timedelta(seconds=20))
        self.assertIsNotNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )

    def test_lookup_does_not_load_team_event_metadata(self) -> None:
        self.register()
        with CaptureQueriesContext(connection) as queries:
            registration = self.registry.lookup(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        self.assertIsNotNone(registration)
        for query in queries.captured_queries:
            self.assertNotIn('"event_names"', query["sql"])
            self.assertNotIn('"event_properties"', query["sql"])

    @parameterized.expand([("expired",), ("revoked",)])
    def test_inactive_execution_cannot_renew_register_or_mint(self, reason: str) -> None:
        self.register()
        if reason == "expired":
            self.clock.shift(AGENT_EGRESS_LEASE_DURATION)
        else:
            self.assertTrue(
                self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
            )
        self.assertIsNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        self.assertIsNone(
            self.registry.renew(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        with self.assertRaises(ValueError):
            self.register()
        with self.assertRaises(ValueError):
            self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )

    @parameterized.expand([("active",), ("expired",), ("revoked",)])
    def test_replacement_keeps_old_execution_retired(self, state: str) -> None:
        self.register()
        if state == "expired":
            self.clock.shift(AGENT_EGRESS_LEASE_DURATION)
        elif state == "revoked":
            self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        self.registry = AgentEgressRegistry(region="test-us")
        previous = self.registry.latest(team_id=self.team.id, run_id=self.task_run.id)
        assert previous is not None
        self.assertEqual(previous.execution_id, self.execution_id)
        self.assertEqual(previous.actor_epoch, 1)
        replacement_id = uuid4()
        replacement = self.register(execution_id=replacement_id, previous_execution_id=previous.execution_id)
        self.assertEqual(replacement.actor_epoch, previous.actor_epoch + 1)
        self.assertEqual(self.registry.latest(team_id=self.team.id, run_id=self.task_run.id), replacement)
        self.assertEqual(
            self.register(execution_id=replacement_id, previous_execution_id=previous.execution_id), replacement
        )

        self.assertIsNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        self.assertIsNone(
            self.registry.renew(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        self.assertFalse(
            self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        with self.assertRaises(ValueError):
            self.register()
        with self.assertRaises(ValueError):
            self.register(execution_id=uuid4(), previous_execution_id=self.execution_id)
        with self.assertRaises(ValueError):
            self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        self.assertEqual(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=replacement_id),
            replacement,
        )

    def test_initial_registration_cannot_restart_a_revoked_run(self) -> None:
        self.register()
        self.registry.revoke(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        with self.assertRaises(ValueError):
            self.register(execution_id=uuid4())

    @parameterized.expand([(TaskRun.Status.COMPLETED,), (TaskRun.Status.FAILED,), (TaskRun.Status.CANCELLED,)])
    def test_terminal_run_loses_authority_without_waiting_for_lease(self, status: str) -> None:
        self.register()
        TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(status=status)
        self.assertIsNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        self.assertIsNone(
            self.registry.renew(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        with self.assertRaises(ValueError):
            self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        with self.assertRaises(ValueError):
            self.register(execution_id=uuid4(), previous_execution_id=self.execution_id)

    @parameterized.expand([("team",), ("run",), ("execution",), ("region",)])
    def test_lookup_and_mutation_require_the_full_scope(self, mismatch: str) -> None:
        registration = self.register()
        team_id = self.other_team.id if mismatch == "team" else self.team.id
        run_id = uuid4() if mismatch == "run" else self.task_run.id
        execution_id = uuid4() if mismatch == "execution" else self.execution_id
        registry = AgentEgressRegistry(region="test-eu") if mismatch == "region" else self.registry

        self.assertEqual(
            registry.latest(team_id=team_id, run_id=run_id), registration if mismatch == "execution" else None
        )
        self.assertIsNone(registry.lookup(team_id=team_id, run_id=run_id, execution_id=execution_id))
        self.assertIsNone(registry.renew(team_id=team_id, run_id=run_id, execution_id=execution_id))
        self.assertFalse(registry.revoke(team_id=team_id, run_id=run_id, execution_id=execution_id))
        with self.assertRaises((ValueError, TaskRun.DoesNotExist)):
            registry.issue_capability(team_id=team_id, run_id=run_id, execution_id=execution_id)
        self.assertEqual(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id),
            registration,
        )

    def test_rebinding_actor_allocates_a_new_epoch(self) -> None:
        registration = self.register()
        self.assertEqual(registration.actor_epoch, 1)
        with self.assertRaises(ValueError):
            self.register(
                execution_id=uuid4(),
                previous_execution_id=self.execution_id,
                actor_id=self.other_actor.id,
            )
        Task.objects.filter(id=self.task_run.task_id, team_id=self.team.id).update(created_by_id=self.other_actor.id)
        with self.assertRaises(ValueError):
            self.register(
                execution_id=uuid4(),
                previous_execution_id=self.execution_id,
                actor_id=self.actor.id,
            )
        replacement = self.register(
            execution_id=uuid4(), previous_execution_id=self.execution_id, actor_id=self.other_actor.id
        )
        self.assertEqual(replacement.actor_epoch, 2)

    @parameterized.expand(
        [("owner",), ("ownership_version",), ("inactive",), ("access",), ("deleted",), ("cancel_requested",)]
    )
    def test_changed_actor_authority_cannot_keep_a_live_registration(self, change: str) -> None:
        self.register()
        if change == "owner":
            Task.objects.filter(id=self.task_run.task_id, team_id=self.team.id).update(
                created_by_id=self.other_actor.id
            )
        elif change == "ownership_version":
            state = {TASK_OWNERSHIP_VERSION_STATE_KEY: str(uuid4())}
            Task.objects.filter(id=self.task_run.task_id, team_id=self.team.id).update(state=state)
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(state=state)
        elif change == "inactive":
            User.objects.filter(id=self.actor.id).update(is_active=False)
        elif change == "access":
            OrganizationMembership.objects.filter(
                user_id=self.actor.id, organization_id=self.team.organization_id
            ).delete()
        elif change == "cancel_requested":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(
                state={"cancel_requested_at": timezone.now().isoformat()}
            )
        else:
            Task.objects.filter(id=self.task_run.task_id, team_id=self.team.id).update(deleted=True)
        self.assertIsNone(
            self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        self.assertIsNone(
            self.registry.renew(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
        )
        with self.assertRaises(ValueError):
            self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
        with self.assertRaises(ValueError):
            self.register()

    @parameterized.expand(
        [
            ("localhost:8443", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, True),
            ("run-a.egress.example.com:443", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, True),
            ("Other.example.com", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, False),
            ("127.0.0.1", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, False),
            ("run.example.com:0443", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, False),
            ("run.example.com/path", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1, False),
            ("run.example.com", "", 1, False),
            ("run.example.com", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB", 1, False),
            ("run.example.com", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 0, False),
        ]
    )
    def test_binding_validation(self, authority: str, fingerprint: str, actor_id: int, valid: bool) -> None:
        actor_id = self.actor.id if actor_id else 0
        if valid:
            self.register(authority=authority, relay_key_sha256=fingerprint, actor_id=actor_id)
            self.assertIsNotNone(
                self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
            )
        else:
            with self.assertRaises(ValueError):
                self.register(authority=authority, relay_key_sha256=fingerprint, actor_id=actor_id)

    def test_capability_issuance_pins_the_run_key_and_preserves_state(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        self.register()
        TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(state={"preserved": True})

        with override_settings(SANDBOX_JWT_PRIVATE_KEY=pem, SANDBOX_JWT_PRIVATE_KEY_SECONDARY=None):
            reset_sandbox_jwt_key_cache()
            self.addCleanup(reset_sandbox_jwt_key_cache)
            token = self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )
            self.task_run.refresh_from_db()
            self.assertEqual(
                self.task_run.state, {"preserved": True, SANDBOX_JWT_STATE_KID_KEY: get_primary_sandbox_jwt_kid()}
            )
            self.assertEqual(jwt.get_unverified_header(token)["kid"], self.task_run.state[SANDBOX_JWT_STATE_KID_KEY])

    def test_unregistered_execution_cannot_mint(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.issue_capability(
                team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id
            )

    @parameterized.expand([("owner",), ("slack",)])
    def test_permission_failure_does_not_report_revocation(self, actor_source: str) -> None:
        if actor_source == "slack":
            TaskRun.objects.filter(id=self.task_run.id, team_id=self.team.id).update(
                state={"interaction_origin": "slack", "slack_actor_user_id": self.other_actor.id}
            )
            self.register(actor_id=self.other_actor.id)
        else:
            self.register()
        with patch.object(UserPermissions, "current_team", new_callable=PropertyMock, side_effect=OperationalError):
            with self.assertRaises(OperationalError):
                self.registry.lookup(team_id=self.team.id, run_id=self.task_run.id, execution_id=self.execution_id)
