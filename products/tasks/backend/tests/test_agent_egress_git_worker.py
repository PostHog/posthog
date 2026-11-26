from datetime import timedelta
from inspect import unwrap
from typing import TypedDict, cast
from uuid import UUID, uuid4

import time_machine
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.models import Integration, Organization, OrganizationMembership, Team, User
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.user_integration import UserIntegration
from posthog.temporal.common.logger import configure_logger
from posthog.temporal.tests.utils.logger import restored_structlog_config

from products.tasks.backend.logic.services.agent_egress import AgentEgressRegistry
from products.tasks.backend.logic.services.agent_egress_git import (
    AgentEgressGitGrants,
    GitGrantConflict,
    GitGrantUnavailable,
    GitReadCredential,
)
from products.tasks.backend.logic.services.agent_egress_git_worker import (
    publish_agent_egress_git_grant,
    refresh_agent_egress_git_grant,
)
from products.tasks.backend.logic.services.sandbox import ExecutionResult, SandboxBase
from products.tasks.backend.models import AgentEgressRegistration, Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials import (
    RefreshSandboxCredentialsInput,
    refresh_sandbox_credentials,
)
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    _apply_token_locked,
    _live_sandboxes_for_user_integration,
    _propagate_user_token,
)


class GitGrantScope(TypedDict):
    team_id: int
    run_id: UUID
    execution_id: UUID


class CredentialSandbox:
    id = "sb-git-worker"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.commands: list[str] = []

    def is_running(self) -> bool:
        return True

    def write_file(self, path: str, content: bytes, **kwargs: object) -> ExecutionResult:
        self.files[path] = content
        return ExecutionResult(stdout="", stderr="", exit_code=0)

    def execute(self, command: str, **kwargs: object) -> ExecutionResult:
        self.commands.append(command)
        return ExecutionResult(stdout="", stderr="", exit_code=0)


@override_settings(AGENT_EGRESS_REGION="test-us")
class TestAgentEgressGitWorker(TestCase):
    def setUp(self) -> None:
        clock = time_machine.travel("2026-11-25T12:00:00Z", tick=False)
        clock.start()
        self.addCleanup(clock.stop)
        cache.clear()
        organization = Organization.objects.create(name="Synthetic egress")
        self.team = Team.objects.create(organization=organization)
        actor = User.objects.create(email="git-worker@example.com")
        OrganizationMembership.objects.create(organization=organization, user=actor)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="123",
            config={"installation_id": 123, "account": {"name": "example", "type": "Organization"}},
        )
        self.task = Task.objects.create(team=self.team, created_by=actor, repository="example/repo")
        self.task_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "sandbox_id": "sb-git-worker",
                "sandbox_backend": "modal",
                "github_read_access": True,
                "repositories": ["example/repo"],
            },
        )
        self.execution_id = uuid4()
        self.scope: GitGrantScope = {
            "team_id": self.team.id,
            "run_id": self.task_run.id,
            "execution_id": self.execution_id,
        }
        self.registry = AgentEgressRegistry(region="test-us")
        self.registry.register(
            **self.scope,
            actor_id=actor.id,
            authority="run-a.egress.example.com",
            relay_key_sha256="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            sandbox_id="sb-git-worker",
        )
        self.grants = AgentEgressGitGrants(region="test-us")
        self.response = MagicMock(status_code=201)
        self.response.json.return_value = {
            "token": "synthetic-worker-token",
            "expires_at": (timezone.now() + timedelta(minutes=47)).isoformat(),
        }
        self.github_client: MagicMock = self.enterContext(
            patch.object(GitHubIntegrationBase, "client_request", return_value=self.response)
        )

    def publish(self, *, initialize: bool = True) -> bool:
        return publish_agent_egress_git_grant(**self.scope, sandbox_id="sb-git-worker", initialize=initialize)

    def lookup(self) -> tuple[AgentEgressRegistration, GitReadCredential] | None:
        return self.grants.lookup(**self.scope, repository="example/repo")

    @parameterized.expand([("agent_egress_git_reads",), ("github_read_access",)])
    def test_sibling_rotation_and_delayed_delivery_keep_scoped_guests_credential_free(self, flag: str) -> None:
        assert self.task.created_by is not None
        integration = UserIntegration.objects.create(
            user=self.task.created_by, kind="github", integration_id="synthetic-user", config={}, sensitive_config={}
        )
        self.task.github_user_integration = integration
        self.task.save(update_fields=["github_user_integration"])
        TaskRun.update_state_atomic(
            self.task_run.id, updates={"pr_authorship_mode": "user"}, remove_keys=["github_read_access"]
        )
        sibling = Task.objects.create(
            team=self.team,
            created_by=self.task.created_by,
            repository="example/sibling",
            github_user_integration=integration,
        )
        TaskRun.objects.create(
            task=sibling,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-sibling", "pr_authorship_mode": "user"},
        )
        delayed = next(
            row for row in _live_sandboxes_for_user_integration(integration.id) if row.run_id == str(self.task_run.id)
        )
        TaskRun.update_state_atomic(self.task_run.id, updates={flag: True})
        protected, ordinary = CredentialSandbox(), CredentialSandbox()
        ordinary.id = "sb-sibling"
        sandboxes = {protected.id: protected, ordinary.id: ordinary}
        with patch(
            "products.tasks.backend.logic.services.sandbox.get_sandbox_class_for_sandbox_id",
            return_value=MagicMock(get_by_id=lambda sandbox_id: sandboxes[sandbox_id]),
        ):
            self.assertFalse(
                _apply_token_locked(
                    cast(SandboxBase, protected),
                    ["example/repo"],
                    "synthetic-sibling-token",
                    delayed.run_id,
                    delayed.owner_id,
                    task_id=delayed.task_id,
                )
            )
            self.assertEqual(
                {row.sandbox_id for row in _live_sandboxes_for_user_integration(integration.id)}, {ordinary.id}
            )
            self.assertEqual(_propagate_user_token(integration.id, "synthetic-sibling-token"), 1)
        self.assertEqual(protected.files, {})
        self.assertEqual(protected.commands, [])
        self.assertIn(b"synthetic-sibling-token", b"".join(ordinary.files.values()))

    @parameterized.expand([("legacy", False), ("brokered", True)])
    def test_existing_refresh_activity_rotates_the_live_execution_grant(self, _name: str, brokered: bool) -> None:
        self.assertTrue(self.publish())
        first = self.lookup()
        assert first is not None
        self.assertEqual(first[1].expires_at, timezone.now() + timedelta(minutes=47))
        self.assertEqual(
            self.github_client.call_args.kwargs["json_body"],
            {"permissions": {"contents": "read", "metadata": "read"}, "repositories": ["repo"]},
        )
        self.assertFalse(self.publish())
        self.github_client.assert_called_once()
        TaskRun.update_state_atomic(
            self.task_run.id,
            updates={
                "agent_egress_probe": {"execution_id": str(self.execution_id), "publish_git_read_grant": True},
                "agent_egress_git_reads": brokered,
            },
        )
        self.response.json.return_value = {
            "token": "synthetic-refreshed-token",
            "expires_at": (timezone.now() + timedelta(minutes=53)).isoformat(),
        }
        ctx = TaskProcessingContext(
            task_id=str(self.task.id),
            run_id=str(self.task_run.id),
            team_id=self.team.id,
            team_uuid=str(self.team.uuid),
            organization_id=str(self.team.organization_id),
            github_integration_id=None if brokered else self.integration.id,
            repository="example/repo",
            distinct_id="synthetic-worker",
            state=self.task_run.state,
        )
        sandbox = CredentialSandbox()
        with (
            restored_structlog_config(),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.get_sandbox_class_for_sandbox_id",
                return_value=MagicMock(get_by_id=lambda _: sandbox),
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
        ):
            configure_logger(cache_logger_on_first_use=False)
            outcome = ActivityEnvironment().run(
                unwrap(refresh_sandbox_credentials), RefreshSandboxCredentialsInput(context=ctx, sandbox_id=sandbox.id)
            )
        if brokered:
            self.assertEqual(sandbox.files, {})
            self.assertEqual(sandbox.commands, [])
        else:
            self.assertIn(b"synthetic-refreshed-token", b"".join(sandbox.files.values()))
        self.assertEqual("github" in outcome.refreshed_kinds, not brokered)
        refreshed = self.lookup()
        assert refreshed is not None
        self.assertNotEqual(first[0].git_read_grant_version, refreshed[0].git_read_grant_version)
        self.assertEqual(refreshed[1].token.get_secret_value(), "synthetic-refreshed-token")
        self.assertEqual(refreshed[1].expires_at, timezone.now() + timedelta(minutes=53))
        self.assertNotIn("synthetic-refreshed-token", repr(outcome))
        assert refreshed[0].git_read_grant_version is not None
        self.grants.clear(**self.scope, version=refreshed[0].git_read_grant_version)
        self.github_client.reset_mock()
        self.assertFalse(self.publish())
        self.assertFalse(self.publish(initialize=False))
        self.github_client.assert_not_called()
        self.assertIsNone(self.lookup())

    @parameterized.expand([("enabled",), ("disabled",), ("different_execution",)])
    def test_refresh_recovers_initial_owner_lookup_failure_only_when_opted_in(self, mode: str) -> None:
        self.integration.config = {"installation_id": 123}
        self.integration.save(update_fields=["config"])
        self.response.status_code = 503
        self.assertFalse(self.publish())
        self.assertIsNone(self.lookup())
        state = {
            "agent_egress_probe": {
                "execution_id": str(uuid4() if mode == "different_execution" else self.execution_id),
                "publish_git_read_grant": mode != "disabled",
            }
        }
        TaskRun.update_state_atomic(self.task_run.id, updates=state)
        owner = MagicMock(status_code=200)
        owner.json.return_value = {"account": {"login": "example", "type": "Organization"}}
        self.response.status_code = 201
        self.github_client.side_effect = [owner, self.response]
        with time_machine.travel(timezone.now() + timedelta(minutes=5, seconds=1), tick=False):
            AgentEgressRegistration.objects.for_team(self.team.id).filter(execution_id=self.execution_id).update(
                lease_expires_at=timezone.now() + timedelta(seconds=30)
            )
            ctx = TaskProcessingContext(
                task_id=str(self.task.id),
                run_id=str(self.task_run.id),
                team_id=self.team.id,
                team_uuid=str(self.team.uuid),
                organization_id=str(self.team.organization_id),
                github_integration_id=self.integration.id,
                repository="example/repo",
                distinct_id="synthetic-worker",
                state=state,
            )
            refresh_agent_egress_git_grant(ctx, sandbox_id="sb-git-worker")
            grant = self.lookup()
            if mode == "enabled":
                assert grant is not None
                self.assertEqual(grant[1].token.get_secret_value(), "synthetic-worker-token")
            else:
                self.assertIsNone(grant)

    @parameterized.expand([("provider",), ("expired",), ("long_lived",), ("invalid_token",)])
    def test_mint_failure_keeps_the_old_grant_and_redacts_diagnostics(self, failure: str) -> None:
        self.assertTrue(self.publish())
        before = self.lookup()
        if failure == "provider":
            self.github_client.side_effect = RuntimeError("synthetic-secret-in-provider-error")
        else:
            self.response.json.return_value = {
                "token": "synthetic-secret-in-provider-error\n" if failure == "invalid_token" else "synthetic-token",
                "expires_at": (
                    timezone.now() + timedelta(minutes={"expired": 0, "long_lived": 61, "invalid_token": 47}[failure])
                ).isoformat(),
            }
        with self.assertRaisesRegex(GitGrantUnavailable, "^Git credential (mint|publication) unavailable$"):
            self.publish(initialize=False)
        ctx = TaskProcessingContext(
            task_id=str(self.task.id),
            run_id=str(self.task_run.id),
            team_id=self.team.id,
            team_uuid=str(self.team.uuid),
            organization_id=str(self.team.organization_id),
            github_integration_id=self.integration.id,
            repository="example/repo",
            distinct_id="synthetic-worker",
            state={"agent_egress_probe": {"execution_id": str(self.execution_id)}},
        )
        with self.assertLogs("products.tasks.backend.logic.services.agent_egress_git_worker", level="WARNING") as logs:
            refresh_agent_egress_git_grant(ctx, sandbox_id="sb-git-worker")
        self.assertNotIn("synthetic-secret-in-provider-error", str(logs.output))
        self.assertEqual(logs.records[0].__dict__["error_type"], "GitGrantUnavailable")
        self.assertIsNone(logs.records[0].exc_info)
        self.assertEqual(before, self.lookup())

    @parameterized.expand(
        [
            ("write_run",),
            ("multiple_repos",),
            ("missing_integration",),
            ("unpublished",),
            ("wrong_sandbox",),
            ("public_repository",),
        ]
    )
    def test_ineligible_refresh_does_not_mint(self, case: str) -> None:
        if case == "write_run":
            TaskRun.update_state_atomic(self.task_run.id, updates={"github_read_access": False})
        elif case == "multiple_repos":
            TaskRun.update_state_atomic(self.task_run.id, updates={"repositories": ["example/repo", "example/second"]})
        elif case == "missing_integration":
            self.integration.delete()
        elif case == "wrong_sandbox":
            self.assertFalse(publish_agent_egress_git_grant(**self.scope, sandbox_id="sb-other", initialize=True))
        elif case == "public_repository":
            TaskRun.update_state_atomic(self.task_run.id, updates={"repositories": ["posthog/hedgebox"]})
        if case != "wrong_sandbox":
            self.assertFalse(self.publish(initialize=case != "unpublished"))
        self.github_client.assert_not_called()
        self.assertIsNone(self.lookup())

    def test_rejected_repository_scope_does_not_publish_a_grant(self) -> None:
        self.response.status_code = 422
        self.response.json.return_value = {"message": "Repository is not installed"}
        self.assertFalse(self.publish())
        self.assertIsNone(self.lookup())

    @parameterized.expand(
        [("revoked",), ("replaced",), ("repository_changed",), ("newer_grant",), ("installation_changed",)]
    )
    def test_authority_changes_during_mint_cannot_publish(self, change: str) -> None:
        self.assertTrue(self.publish())
        original = self.lookup()
        assert original is not None

        def mint(*args: object, **kwargs: object) -> MagicMock:
            if change == "revoked":
                self.registry.revoke(**self.scope, revoked_by="test", reason="cancelled")
            elif change == "replaced":
                TaskRun.update_state_atomic(self.task_run.id, updates={"sandbox_id": "sb-replacement"})
            elif change == "repository_changed":
                TaskRun.update_state_atomic(self.task_run.id, updates={"repositories": ["example/second"]})
            elif change == "installation_changed":
                self.integration.integration_id = "456"
                self.integration.save(update_fields=["integration_id"])
            else:
                self.grants.publish(
                    **self.scope,
                    credential=original[1],
                    version=uuid4(),
                    previous_version=original[0].git_read_grant_version,
                )
            return self.response

        self.github_client.side_effect = mint
        if change in ("repository_changed", "installation_changed"):
            self.assertFalse(self.publish(initialize=False))
        else:
            with self.assertRaises(GitGrantConflict if change == "newer_grant" else ValueError):
                self.publish(initialize=False)
        current = self.lookup()
        if change == "newer_grant":
            assert current is not None
            self.assertNotEqual(current[0].git_read_grant_version, original[0].git_read_grant_version)
        else:
            self.assertIsNone(current)


@override_settings(AGENT_EGRESS_REGION="test-us")
class TestAgentEgressGitWorkerAutocommit(TransactionTestCase):
    @time_machine.travel("2026-11-25T12:00:00Z", tick=False)
    def test_loop_publication_locks_owner_without_holding_transaction_during_mint(self) -> None:
        organization = Organization.objects.create(name="Synthetic loop")
        team = Team.objects.create(organization=organization)
        actor = User.objects.create(email="loop-worker@example.com")
        OrganizationMembership.objects.create(organization=organization, user=actor)
        Integration.objects.create(
            team=team,
            kind="github",
            integration_id="456",
            config={"account": {"name": "example", "type": "Organization"}},
        )
        task = Task.objects.create(team=team, created_by=actor, repository="example/repo")
        run = TaskRun.objects.create(
            team=team,
            task=task,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_id": "sb-loop", "github_read_access": True, "loop_id": str(uuid4())},
        )
        scope: GitGrantScope = {"team_id": team.id, "run_id": run.id, "execution_id": uuid4()}
        AgentEgressRegistry(region="test-us").register(
            **scope,
            actor_id=actor.id,
            authority="loop.egress.example.com",
            relay_key_sha256="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            sandbox_id="sb-loop",
        )

        def mint(*args: object, **kwargs: object) -> MagicMock:
            self.assertTrue(transaction.get_autocommit())
            response = MagicMock(status_code=201)
            response.json.return_value = {
                "token": "synthetic-loop-token",
                "expires_at": (timezone.now() + timedelta(minutes=45)).isoformat(),
            }
            return response

        with patch.object(GitHubIntegrationBase, "client_request", side_effect=mint):
            self.assertTrue(publish_agent_egress_git_grant(**scope, sandbox_id="sb-loop", initialize=True))
        grant = AgentEgressGitGrants(region="test-us").lookup(**scope, repository="example/repo")
        assert grant is not None
        self.assertEqual(grant[1].token.get_secret_value(), "synthetic-loop-token")
