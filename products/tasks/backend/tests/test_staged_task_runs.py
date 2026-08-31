import hmac
import json
import uuid
import hashlib
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, current_thread
from typing import Literal, cast

from unittest.mock import AsyncMock, Mock, patch

from django.db import OperationalError, close_old_connections, models
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models import Integration, Organization, Team, User
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.facade import api as tasks_api
from products.tasks.backend.facade.contracts import (
    AdvanceStagedTaskInput,
    CancelStagedTaskInput,
    CapabilityManifestDTO,
    CreateStagedTaskInput,
    GetStagedArtifactLifecycleInput,
    GetStagedExecutionByIdempotencyInput,
    GetStagedTaskByIdempotencyInput,
    PublicationLeaseReservationDTO,
    RepositoryBaseBindingDTO,
    RepositoryGrantBindingDTO,
    ResolveStagedRepositoryBaseInput,
    RevokeStagedTaskCapabilitiesInput,
)
from products.tasks.backend.logic.services import staged_task_runs
from products.tasks.backend.logic.services.credential_free_workspace import resolve_credential_free_repository_workspace
from products.tasks.backend.logic.services.loop_runs import fire_loop
from products.tasks.backend.logic.services.publication_service import (
    PublicationProposal,
    publish_staged_draft_publication,
)
from products.tasks.backend.logic.services.publication_transport import (
    BranchCreation,
    DraftPullRequest,
    GitHubPublicationClient,
    NormalizedTreeOperation,
)
from products.tasks.backend.logic.services.staged_task_runs import (
    MAX_STAGED_PUBLICATION_LEASE_LIFETIME,
    revoke_staged_capabilities_for_terminal_run,
    terminalize_staged_task_run,
    validate_staged_execution_for_provisioning,
)
from products.tasks.backend.loop_lifecycle import pause_loops_for_deactivated_user
from products.tasks.backend.models import (
    Loop,
    Task,
    TaskDraftPublication,
    TaskPublicationLease,
    TaskRun,
    TaskStagedRunTransition,
)
from products.tasks.backend.temporal.client import redispatch_orphaned_task_run
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
    _validate_staged_execution_context,
)


class _DefaultRepositoryGrant:
    pass


_DEFAULT_REPOSITORY_GRANT = _DefaultRepositoryGrant()


@override_settings(GITHUB_APP_SLUG="posthog")
class TestStagedTaskFacade(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Staged facade org")
        self.team = Team.objects.create(organization=self.organization, name="Staged facade team")
        self.user = User.objects.create(email="staged-facade@example.com")
        self.caller_id = uuid.uuid4()
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id="installation-1",
            config={"installation_id": "installation-1"},
            repository_cache=[{"full_name": "posthog/posthog", "can_push": True, "private": True}],
            errors="",
        )

    def _create_input(
        self,
        *,
        repository: str | None = "posthog/posthog",
        repository_grant: RepositoryGrantBindingDTO | None | _DefaultRepositoryGrant = _DEFAULT_REPOSITORY_GRANT,
        idempotency_key: str = "pulse-run-1:implementation",
    ) -> CreateStagedTaskInput:
        return CreateStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            actor_id=self.user.id,
            idempotency_key=idempotency_key,
            origin_product=Task.OriginProduct.WORKFLOW,
            title="Analyze a repository change",
            description="Analyze before any execution capability is granted.",
            repository=repository,
            repository_grant=(
                self._repository_grant() if isinstance(repository_grant, _DefaultRepositoryGrant) else repository_grant
            ),
            repository_base=(
                RepositoryBaseBindingDTO(
                    repository="posthog/posthog",
                    base_sha="a" * 40,
                    base_branch="main",
                )
                if repository is not None
                else None
            ),
            analysis_manifest=CapabilityManifestDTO(version=1, phase="analysis", capabilities=("read",)),
        )

    def _reservation(self) -> PublicationLeaseReservationDTO:
        return PublicationLeaseReservationDTO(
            logical_artifact_key="proposal-1:draft-pr:v1",
            action_key="proposal-1",
            repository="posthog/posthog",
            base_sha="a" * 40,
            base_branch="main",
            commit_message="Create draft",
            pr_title="Draft",
            pr_body="",
            github_integration_id=self.github_integration.id,
            github_installation_id="installation-1",
            grant_version="1",
            starts_before=timezone.now() + timedelta(minutes=8),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def _repository_grant(self) -> RepositoryGrantBindingDTO:
        return RepositoryGrantBindingDTO(
            repository="posthog/posthog",
            github_integration_id=self.github_integration.id,
            github_installation_id="installation-1",
            grant_version="1",
        )

    def test_create_staged_task_is_idempotent_and_analysis_cannot_publish(self) -> None:
        request = self._create_input()

        first = tasks_api.create_staged_task(request)
        second = tasks_api.create_staged_task(request)

        self.assertEqual(first, second)
        self.assertEqual(Task.objects.filter(team=self.team).count(), 1)
        self.assertEqual(TaskRun.objects.filter(task_id=first.task_id).count(), 1)
        analysis_run = TaskRun.objects.get(id=first.analysis_run_id)
        self.assertEqual(analysis_run.state["staged_manifest"]["phase"], "analysis")
        self.assertFalse(analysis_run.state["staged_manifest"]["bindings"]["publication_allowed"])
        self.assertFalse(analysis_run.state["create_pr"])
        self.assertFalse(analysis_run.state["auto_publish"])

    def test_staged_task_lookup_requires_the_exact_caller_binding(self) -> None:
        request = self._create_input()
        created = tasks_api.create_staged_task(request)

        recovered = tasks_api.get_staged_task_by_idempotency(
            GetStagedTaskByIdempotencyInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                idempotency_key=request.idempotency_key,
            )
        )

        self.assertEqual(recovered, created)
        with self.assertRaisesRegex(ValueError, "staged_task_identity_mismatch"):
            tasks_api.get_staged_task_by_idempotency(
                GetStagedTaskByIdempotencyInput(
                    team_id=self.team.id,
                    caller_id=uuid.uuid4(),
                    idempotency_key=request.idempotency_key,
                )
            )

    def test_cancel_before_a_successor_exists_cancels_the_analysis_run(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())

        with patch(
            "products.tasks.backend.facade.cancellation.cancel_task_run",
            return_value=("accepted", None),
        ) as cancel_run:
            cancelled = tasks_api.cancel_staged_task(
                CancelStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=created.analysis_run_id,
                )
            )

        self.assertEqual(cancelled.outcome, "accepted")
        self.assertIsNone(cancelled.execution_run_id)
        cancel_run.assert_called_once_with(
            created.analysis_run_id,
            created.task_id,
            self.team.id,
            reason="Proactive subscription run stopped",
            source="subscription_pulse",
        )

    def test_analysis_persists_exact_base_schema_and_pulse_scope(self) -> None:
        output_schema = {
            "type": "object",
            "properties": {"actions": {"type": "array", "maxItems": 3}},
            "required": ["actions"],
        }
        created = tasks_api.create_staged_task(
            replace(self._create_input(), output_schema=output_schema, mcp_scope_preset="pulse_analysis")
        )

        task = Task.objects.get(id=created.task_id)
        analysis_run = TaskRun.objects.get(id=created.analysis_run_id)
        workspace = resolve_credential_free_repository_workspace(str(analysis_run.id), "modal")

        self.assertEqual(task.json_schema, output_schema)
        self.assertEqual(analysis_run.state["posthog_mcp_scopes"], "pulse_analysis")
        self.assertEqual(analysis_run.state["pending_dispatch"]["posthog_mcp_scopes"], "pulse_analysis")
        self.assertIsNotNone(workspace)
        assert workspace is not None
        self.assertEqual(workspace.repository, "posthog/posthog")
        self.assertEqual(workspace.base_sha, "a" * 40)

    def test_staged_context_window_is_immutable_and_copies_to_execution(self) -> None:
        request = replace(self._create_input(), context_window="200k")
        created = tasks_api.create_staged_task(request)
        analysis_run = TaskRun.objects.get(id=created.analysis_run_id)
        self.assertEqual(analysis_run.state["context_window"], "200k")
        self.assertEqual(tasks_api.create_staged_task(request), created)

        with self.assertRaisesRegex(ValueError, "staged_task_identity_mismatch"):
            tasks_api.create_staged_task(replace(request, context_window="1m"))

        analysis_run.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        analysis_run.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:context-window-execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )

        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        self.assertEqual(successor.state["context_window"], "200k")

    def test_staged_context_window_rejects_unsupported_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "context_window"):
            tasks_api.create_staged_task(
                replace(self._create_input(), context_window=cast(Literal["200k", "1m"], "20k"))
            )

    def test_experiment_only_execution_does_not_create_publication_lease(self) -> None:
        created = tasks_api.create_staged_task(replace(self._create_input(), mcp_scope_preset="pulse_analysis"))
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])

        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:experiment-execution",
                execution_manifest=CapabilityManifestDTO(
                    version=1,
                    phase="execution",
                    capabilities=("read", "experiment_draft"),
                ),
                reservation=None,
            )
        )

        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        self.assertIsNone(advanced.publication_lease_id)
        self.assertFalse(successor.state["staged_manifest"]["bindings"]["publication_allowed"])
        self.assertEqual(successor.state["posthog_mcp_scopes"], "pulse_analysis")
        self.assertEqual(TaskPublicationLease.objects.unscoped().filter(task_id=created.task_id).count(), 0)

        cancel_input = CancelStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=created.analysis_run_id,
        )
        with patch(
            "products.tasks.backend.facade.cancellation.cancel_task_run",
            return_value=("accepted", None),
        ) as cancel_run:
            cancelled = tasks_api.cancel_staged_task(cancel_input)

        self.assertTrue(cancelled.revoked)
        self.assertEqual(cancelled.outcome, "accepted")
        cancel_run.assert_called_once_with(
            advanced.execution_run_id,
            created.task_id,
            self.team.id,
            reason="Proactive subscription run stopped",
            source="subscription_pulse",
        )
        self.assertFalse(
            tasks_api.revoke_staged_task_capabilities(
                RevokeStagedTaskCapabilitiesInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=created.analysis_run_id,
                )
            ).revoked
        )
        successor.refresh_from_db()
        self.assertIs(successor.state.get("staged_capabilities_revoked"), True)

    def test_combined_execution_keeps_one_pr_lease_and_explicit_experiment_capability(self) -> None:
        created = tasks_api.create_staged_task(replace(self._create_input(), mcp_scope_preset="pulse_analysis"))
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])

        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:combined-execution",
                execution_manifest=CapabilityManifestDTO(
                    version=1,
                    phase="execution",
                    capabilities=("read", "draft", "experiment_draft"),
                ),
                reservation=self._reservation(),
            )
        )

        self.assertIsNotNone(advanced.publication_lease_id)
        experiment_binding = tasks_api.resolve_staged_task_capability_binding(
            team_id=self.team.id,
            task_id=created.task_id,
            required_capability="experiment_draft",
        )
        self.assertIsNotNone(experiment_binding)
        assert experiment_binding is not None
        self.assertEqual(experiment_binding.task_run_id, advanced.execution_run_id)

    def test_repository_task_requires_a_trusted_github_grant_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "staged_repository_grant_required"):
            tasks_api.create_staged_task(self._create_input(repository_grant=None))

    def test_tasks_resolves_the_exact_repository_base_through_the_bound_integration(self) -> None:
        with (
            patch.object(staged_task_runs.GitHubIntegration, "organization", return_value="posthog"),
            patch.object(staged_task_runs.GitHubIntegration, "get_default_branch", return_value="main"),
            patch.object(
                staged_task_runs.GitHubIntegration,
                "get_branch_info",
                return_value={"success": True, "exists": True, "commit_sha": "b" * 40},
            ),
        ):
            binding = tasks_api.resolve_staged_repository_base(
                ResolveStagedRepositoryBaseInput(
                    team_id=self.team.id,
                    repository_grant=self._repository_grant(),
                )
            )

        self.assertEqual(binding.repository, "posthog/posthog")
        self.assertEqual(binding.base_sha, "b" * 40)
        self.assertEqual(binding.base_branch, "main")

    def test_advance_requires_reservation_then_reuses_successor_and_lease(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state["snapshot_external_id"] = "modal-analysis-snapshot"
        source.state["sandbox_backend"] = "modal"
        source.save(update_fields=["state"])
        request = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=created.analysis_run_id,
            idempotency_key="proposal-1:execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
            reservation=None,
        )

        with self.assertRaisesRegex(ValueError, "staged_task_reservation_required"):
            tasks_api.advance_staged_task(request)

        request = replace(request, reservation=self._reservation())
        first = tasks_api.advance_staged_task(request)
        second = tasks_api.advance_staged_task(request)

        self.assertEqual(first, second)
        self.assertEqual(TaskRun.objects.filter(task_id=created.task_id).count(), 2)
        successor = TaskRun.objects.get(id=first.execution_run_id)
        self.assertEqual(successor.state["resume_from_run_id"], str(source.id))
        self.assertEqual(successor.state["snapshot_external_id"], "modal-analysis-snapshot")
        self.assertEqual(successor.state["staged_manifest"]["phase"], "execution")
        self.assertTrue(successor.state["staged_manifest"]["bindings"]["publication_allowed"])
        self.assertEqual(TaskPublicationLease.objects.unscoped().filter(task_id=created.task_id).count(), 1)
        task = Task.objects.get(id=created.task_id)
        assert first.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=first.publication_lease_id)
        self.assertEqual(task.github_integration_id, self.github_integration.id)
        self.assertEqual(lease.github_integration_id, self.github_integration.id)
        self.assertEqual(lease.github_installation_id, "installation-1")
        self.assertEqual(lease.head_branch, f"codex/{lease.id.hex}")

        with self.assertRaisesRegex(ValueError, "publication_lease_binding_mismatch"):
            tasks_api.advance_staged_task(replace(request, reservation=replace(self._reservation(), base_sha="b" * 40)))

    def test_staged_execution_lookup_recovers_only_the_exact_caller_transition(self) -> None:
        created = tasks_api.create_staged_task(self._create_input(repository=None, repository_grant=None))
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        idempotency_key = "proposal-1:execution-lookup"
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key=idempotency_key,
                execution_manifest=CapabilityManifestDTO(
                    version=1,
                    phase="execution",
                    capabilities=("read", "experiment_draft"),
                ),
                reservation=None,
            )
        )

        recovered = tasks_api.get_staged_execution_by_idempotency(
            GetStagedExecutionByIdempotencyInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key=idempotency_key,
            )
        )

        self.assertEqual(recovered, advanced)
        self.assertIsNone(
            tasks_api.get_staged_execution_by_idempotency(
                GetStagedExecutionByIdempotencyInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=source.id,
                    idempotency_key="missing",
                )
            )
        )
        with self.assertRaisesRegex(ValueError, "staged_task_identity_mismatch"):
            tasks_api.get_staged_execution_by_idempotency(
                GetStagedExecutionByIdempotencyInput(
                    team_id=self.team.id,
                    caller_id=uuid.uuid4(),
                    task_id=created.task_id,
                    source_run_id=source.id,
                    idempotency_key=idempotency_key,
                )
            )

    def test_repository_task_rejects_cross_team_or_inactive_github_grant(self) -> None:
        other_organization = Organization.objects.create(name="Other staged facade org")
        other_team = Team.objects.create(organization=other_organization, name="Other staged facade team")
        other_integration = Integration.objects.create(
            team=other_team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id="installation-1",
            config={"installation_id": "installation-1"},
            errors="",
        )
        cross_team_grant = replace(self._repository_grant(), github_integration_id=other_integration.id)

        with self.assertRaisesRegex(ValueError, "staged_repository_grant_inactive"):
            tasks_api.create_staged_task(self._create_input(repository_grant=cross_team_grant))

        self.github_integration.config[INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY] = 1
        self.github_integration.save(update_fields=["config"])
        with self.assertRaisesRegex(ValueError, "staged_repository_grant_inactive"):
            tasks_api.create_staged_task(self._create_input())

    def test_repository_task_rejects_a_github_integration_with_refresh_failure(self) -> None:
        self.github_integration.errors = ERROR_TOKEN_REFRESH_FAILED
        self.github_integration.save(update_fields=["errors"])

        with self.assertRaisesRegex(ValueError, "staged_repository_grant_inactive"):
            tasks_api.create_staged_task(self._create_input())

    def test_advance_requires_the_immutable_repository_grant_binding(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        request = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=source.id,
            idempotency_key="proposal-1:execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
            reservation=replace(self._reservation(), grant_version="different"),
        )

        with self.assertRaisesRegex(ValueError, "staged_repository_grant_mismatch"):
            tasks_api.advance_staged_task(request)

    def test_non_repository_task_rejects_a_repository_grant_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "staged_repository_grant_unexpected"):
            tasks_api.create_staged_task(self._create_input(repository=None))

        created = tasks_api.create_staged_task(self._create_input(repository=None, repository_grant=None))
        task = Task.objects.get(id=created.task_id)
        self.assertIsNone(task.github_integration_id)
        assert task.state is not None
        self.assertNotIn("staged_repository_grant", task.state)

    def test_repositoryless_analysis_provisioning_requires_no_github_binding_or_workspace(self) -> None:
        created = tasks_api.create_staged_task(self._create_input(repository=None, repository_grant=None))
        analysis_run = TaskRun.objects.get(id=created.analysis_run_id)

        self.assertIsNone(validate_staged_execution_for_provisioning(str(analysis_run.id), "modal"))
        self.assertIsNone(resolve_credential_free_repository_workspace(str(analysis_run.id), "modal"))

    def test_repositoryless_experiment_execution_requires_no_github_binding_or_workspace(self) -> None:
        created = tasks_api.create_staged_task(self._create_input(repository=None, repository_grant=None))
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])

        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:repositoryless-experiment-execution",
                execution_manifest=CapabilityManifestDTO(
                    version=1,
                    phase="execution",
                    capabilities=("read", "experiment_draft"),
                ),
                reservation=None,
            )
        )

        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        self.assertIsNone(advanced.publication_lease_id)
        self.assertIsNone(validate_staged_execution_for_provisioning(str(successor.id), "modal"))
        self.assertIsNone(resolve_credential_free_repository_workspace(str(successor.id), "modal"))
        self.assertNotIn("staged_repository", successor.state)
        self.assertNotIn("staged_base_sha", successor.state)

    def test_repositoryless_execution_cannot_request_draft_publication(self) -> None:
        created = tasks_api.create_staged_task(self._create_input(repository=None, repository_grant=None))
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])

        with self.assertRaisesRegex(ValueError, "staged_repository_grant_required"):
            tasks_api.advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=created.analysis_run_id,
                    idempotency_key="proposal-1:repositoryless-draft-execution",
                    execution_manifest=CapabilityManifestDTO(
                        version=1, phase="execution", capabilities=("read", "draft")
                    ),
                    reservation=self._reservation(),
                )
            )

    def test_execution_publication_reservation_is_idempotent_and_server_owned(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )

        self.assertTrue(hasattr(staged_task_runs, "reserve_staged_draft_publication"))
        first = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))
        second = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))

        self.assertEqual(first, second)
        self.assertEqual(first.repository, "posthog/posthog")
        self.assertEqual(first.base_sha, "a" * 40)
        self.assertTrue(first.branch.startswith("codex/"))
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        self.assertEqual(lease.commit_author_name, "PostHog Tasks")
        self.assertEqual(lease.commit_author_email, "tasks@posthog.com")
        self.assertGreater(lease.commit_timestamp or 0, 0)

        self.assertTrue(hasattr(staged_task_runs, "record_staged_draft_publication_bundle"))
        bundle_sha256 = "c" * 64
        staged_task_runs.record_staged_draft_publication_bundle(
            str(advanced.execution_run_id),
            storage_path=f"tasks/draft-publications/{first.publication_id}/{bundle_sha256}.bundle",
            bundle_head_sha="b" * 40,
            bundle_sha256=bundle_sha256,
            bundle_byte_count=1024,
        )
        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=first.publication_id)
        self.assertEqual(publication.status, TaskDraftPublication.Status.UPLOADED)
        self.assertEqual(
            publication.bundle_storage_path,
            f"tasks/draft-publications/{first.publication_id}/{bundle_sha256}.bundle",
        )
        self.assertEqual(publication.bundle_sha256, bundle_sha256)
        self.assertEqual(publication.bundle_byte_count, 1024)

    def test_publication_service_finalizes_the_locked_database_claim(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        reservation = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))
        staged_task_runs.record_staged_draft_publication_bundle(
            str(advanced.execution_run_id),
            storage_path=f"tasks/draft-publications/{reservation.publication_id}/{'c' * 64}.bundle",
            bundle_head_sha="b" * 40,
            bundle_sha256="c" * 64,
            bundle_byte_count=1024,
        )
        transport = Mock()
        client = Mock(spec=GitHubPublicationClient)
        transport.create_commit.return_value = "d" * 40
        transport.create_branch.return_value = BranchCreation.CREATED
        transport.create_pull_request.return_value = DraftPullRequest(
            commit_sha="d" * 40,
            pr_number=42,
            pr_url="https://github.com/posthog/posthog/pull/42",
        )

        published = publish_staged_draft_publication(
            str(advanced.execution_run_id),
            PublicationProposal(
                operations=(NormalizedTreeOperation(path="README.md", mode="100644", content=b"hello"),)
            ),
            transport=transport,
            client_factory=lambda _integration: cast(GitHubPublicationClient, client),
            gate_validator=lambda _run_id: None,
        )

        publication = TaskDraftPublication.objects.unscoped().get(id=reservation.publication_id)
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        self.assertEqual(published.pr_number, 42)
        self.assertEqual(publication.status, TaskDraftPublication.Status.FINALIZED)
        self.assertEqual(lease.status, TaskPublicationLease.Status.FINALIZED)
        self.assertEqual(lease.final_artifact_ref, published.pr_url)
        transport.create_commit.assert_called_once()
        transport.create_branch.assert_called_once()
        transport.create_pull_request.assert_called_once()

        assert advanced.publication_lease_id is not None
        lifecycle_input = GetStagedArtifactLifecycleInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=source.id,
            execution_run_id=advanced.execution_run_id,
            publication_lease_id=advanced.publication_lease_id,
        )
        lifecycle = tasks_api.get_staged_artifact_lifecycle(lifecycle_input)
        assert lifecycle is not None
        self.assertEqual(lifecycle.state, "unknown")

        TaskRun.objects.filter(id=advanced.execution_run_id).update(
            output={"pr_url": published.pr_url, "pr_state": "merged"}
        )
        execution = TaskRun.objects.get(id=advanced.execution_run_id)
        execution.state = {**execution.state, "verified_pr_urls": [published.pr_url]}
        execution.save(update_fields=["state"])
        lifecycle = tasks_api.get_staged_artifact_lifecycle(lifecycle_input)
        assert lifecycle is not None
        self.assertEqual(lifecycle.state, "unknown")

        webhook_secret = "staged-lifecycle-secret"
        payload = {
            "action": "closed",
            "pull_request": {
                "html_url": published.pr_url,
                "merged": True,
                "merged_at": "2026-08-30T10:00:00Z",
                "head": {
                    "ref": execution.branch,
                    "repo": {"full_name": "posthog/posthog"},
                },
            },
            "repository": {"full_name": "posthog/posthog"},
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        signature = "sha256=" + hmac.new(webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        with (
            patch(
                "products.tasks.backend.facade.webhooks.get_github_webhook_secret",
                return_value=webhook_secret,
            ),
            patch("products.tasks.backend.models.posthoganalytics.capture"),
        ):
            response = APIClient().post(
                "/webhooks/github/pr/",
                data=payload_bytes,
                content_type="application/json",
                headers={"x-hub-signature-256": signature, "x-github-event": "pull_request"},
            )

        self.assertEqual(response.status_code, 200)
        lifecycle = tasks_api.get_staged_artifact_lifecycle(lifecycle_input)
        assert lifecycle is not None
        self.assertEqual(lifecycle.state, "merged")
        self.assertEqual(lifecycle.changed_at, datetime(2026, 8, 30, 10, tzinfo=UTC))

        self.assertIsNone(
            tasks_api.get_staged_artifact_lifecycle(
                GetStagedArtifactLifecycleInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=uuid.uuid4(),
                    execution_run_id=advanced.execution_run_id,
                    publication_lease_id=advanced.publication_lease_id,
                )
            )
        )
        for invalid_input in (
            GetStagedArtifactLifecycleInput(
                team_id=self.team.id,
                caller_id=uuid.uuid4(),
                task_id=created.task_id,
                source_run_id=source.id,
                execution_run_id=advanced.execution_run_id,
                publication_lease_id=advanced.publication_lease_id,
            ),
            GetStagedArtifactLifecycleInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                execution_run_id=uuid.uuid4(),
                publication_lease_id=advanced.publication_lease_id,
            ),
            GetStagedArtifactLifecycleInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                execution_run_id=advanced.execution_run_id,
                publication_lease_id=uuid.uuid4(),
            ),
        ):
            with self.subTest(invalid_input=invalid_input):
                self.assertIsNone(tasks_api.get_staged_artifact_lifecycle(invalid_input))

    def test_execution_publication_reservation_is_revoked_with_the_lease(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        reservation = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))

        tasks_api.revoke_staged_task_capabilities(
            RevokeStagedTaskCapabilitiesInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
            )
        )

        publication = TaskDraftPublication.objects.for_team(self.team.id).get(id=reservation.publication_id)
        self.assertEqual(publication.status, TaskDraftPublication.Status.REVOKED)

        transport = Mock()
        with self.assertRaises(TaskInvalidStateError):
            publish_staged_draft_publication(
                str(advanced.execution_run_id),
                PublicationProposal(
                    operations=(NormalizedTreeOperation(path="README.md", mode="100644", content=b"hello"),)
                ),
                transport=transport,
                client_factory=lambda _integration: cast(GitHubPublicationClient, Mock()),
                gate_validator=lambda _run_id: None,
            )

        transport.create_commit.assert_not_called()
        transport.create_branch.assert_not_called()
        transport.create_pull_request.assert_not_called()

    def test_publication_callback_receives_only_locked_exact_bindings(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        reserved = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))

        bound = staged_task_runs.with_validated_staged_draft_publication(
            str(advanced.execution_run_id),
            lambda integration, task, source_run, transition, successor_run, lease, publication: (
                integration.id,
                task.id,
                source_run.id,
                transition.id,
                successor_run.id,
                lease.id,
                publication.id,
            ),
        )

        self.assertEqual(bound[0], self.github_integration.id)
        self.assertEqual(str(bound[-1]), reserved.publication_id)
        publication = TaskDraftPublication.objects.unscoped().get(id=reserved.publication_id)
        mutations = {
            "base_branch": "release",
            "commit_message": "other commit",
            "pr_title": "Other draft",
            "pr_body": "other body",
            "commit_author_name": "Other",
            "commit_author_email": "other@example.com",
            "commit_timestamp": publication.commit_timestamp + 1,
            "expected_github_app_slug": "other-app",
            "expected_github_app_login": "other-app[bot]",
            "branch": f"codex/{'0' * 32}",
        }
        for field, mutated_value in mutations.items():
            with self.subTest(field=field):
                original_value = getattr(publication, field)
                TaskDraftPublication.objects.unscoped().filter(id=publication.id).update(**{field: mutated_value})
                with self.assertRaisesRegex(TaskInvalidStateError, "draft_publication_binding_mismatch"):
                    staged_task_runs.with_validated_staged_draft_publication(
                        str(advanced.execution_run_id),
                        lambda *_args: None,
                    )
                TaskDraftPublication.objects.unscoped().filter(id=publication.id).update(**{field: original_value})

    def test_external_publication_continuation_does_not_expire_the_retained_claim(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        reservation = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))
        staged_task_runs.record_staged_draft_publication_bundle(
            str(advanced.execution_run_id),
            storage_path=f"tasks/draft-publications/{reservation.publication_id}/{'c' * 64}.bundle",
            bundle_head_sha="b" * 40,
            bundle_sha256="c" * 64,
            bundle_byte_count=1024,
        )
        publication = TaskDraftPublication.objects.unscoped().get(id=reservation.publication_id)
        now = timezone.now()
        TaskDraftPublication.objects.unscoped().filter(id=publication.id).update(
            status=TaskDraftPublication.Status.BRANCH_CREATED,
            github_commit_sha="d" * 40,
            commit_created_at=now,
            branch_created_at=now,
        )
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)

        with (
            patch.object(staged_task_runs.django_timezone, "now", return_value=lease.expires_at + timedelta(seconds=1)),
            self.assertRaisesRegex(TaskInvalidStateError, "draft_publication_external_mutation_unavailable"),
        ):
            staged_task_runs.with_validated_staged_draft_publication(
                str(advanced.execution_run_id),
                lambda *_args: None,
                mode="continue_external_mutation",
            )

        lease.refresh_from_db()
        self.assertEqual(lease.status, TaskPublicationLease.Status.ACTIVE)

    def test_cancellation_retains_an_external_attempt_for_read_only_reconciliation(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(
                    version=1,
                    phase="execution",
                    capabilities=("read", "draft", "experiment_draft"),
                ),
                reservation=self._reservation(),
            )
        )
        reservation = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))
        staged_task_runs.record_staged_draft_publication_bundle(
            str(advanced.execution_run_id),
            storage_path=f"tasks/draft-publications/{reservation.publication_id}/{'c' * 64}.bundle",
            bundle_head_sha="b" * 40,
            bundle_sha256="c" * 64,
            bundle_byte_count=1024,
        )
        now = timezone.now()
        TaskDraftPublication.objects.unscoped().filter(id=reservation.publication_id).update(
            status=TaskDraftPublication.Status.PR_CREATING,
            github_commit_sha="d" * 40,
            commit_created_at=now,
            branch_created_at=now,
            pr_creation_started_at=now,
        )
        revoke_input = RevokeStagedTaskCapabilitiesInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=source.id,
        )

        self.assertTrue(tasks_api.revoke_staged_task_capabilities(revoke_input).revoked)
        self.assertFalse(tasks_api.revoke_staged_task_capabilities(revoke_input).revoked)

        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        transition = TaskStagedRunTransition.objects.unscoped().get(id=advanced.transition_id)
        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        self.assertEqual(lease.status, TaskPublicationLease.Status.ACTIVE)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.ADVANCED)
        self.assertIs(successor.state.get("staged_capabilities_revoked"), True)
        self.assertIsNone(
            tasks_api.resolve_staged_task_capability_binding(
                team_id=self.team.id,
                task_id=created.task_id,
                required_capability="experiment_draft",
            )
        )
        reconciled_publication_id = staged_task_runs.with_validated_staged_draft_publication(
            str(advanced.execution_run_id),
            lambda *_args: str(_args[-1].id),
            mode="reconcile_after_expiry",
        )
        self.assertEqual(reconciled_publication_id, reservation.publication_id)
        with self.assertRaisesRegex(TaskInvalidStateError, "draft_publication_external_mutation_unavailable"):
            staged_task_runs.with_validated_staged_draft_publication(
                str(advanced.execution_run_id),
                lambda *_args: None,
                mode="continue_external_mutation",
            )

    def test_lost_dispatch_recovery_keeps_both_staged_phases_read_only(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        execution = TaskRun.objects.get(id=advanced.execution_run_id)
        client = Mock()
        client.start_workflow = AsyncMock()

        with (
            patch("products.tasks.backend.temporal.client.sync_connect", return_value=client),
            patch("products.tasks.backend.temporal.client.posthoganalytics.feature_enabled", return_value=False),
        ):
            self.assertEqual(redispatch_orphaned_task_run(str(source.id)), "recovered")
            self.assertEqual(redispatch_orphaned_task_run(str(execution.id)), "recovered")

        recovered_inputs = [call.args[1] for call in client.start_workflow.call_args_list]
        self.assertEqual([item.create_pr for item in recovered_inputs], [False, False])
        self.assertEqual([item.posthog_mcp_scopes for item in recovered_inputs], ["read_only", "read_only"])

    def test_execution_provisioning_revalidates_the_durable_transition_and_lease(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        successor = TaskRun.objects.get(id=advanced.execution_run_id)

        binding = validate_staged_execution_for_provisioning(str(successor.id), "modal")
        assert binding is not None
        self.assertEqual(binding.repository, "posthog/posthog")
        self.assertEqual(binding.base_sha, "a" * 40)
        successor.state["snapshot_external_id"] = "forged-snapshot"
        successor.save(update_fields=["state"])

        with self.assertRaisesRegex(TaskInvalidStateError, "Staged execution state is invalid"):
            validate_staged_execution_for_provisioning(str(successor.id), "modal")

    def test_execution_provisioning_acquires_durable_locks_in_terminalization_order(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        lock_order: list[str] = []
        original_select_for_update = models.QuerySet.select_for_update

        def observe_lock_order(
            queryset: models.QuerySet[models.Model],
            nowait: bool = False,
            skip_locked: bool = False,
            of: Sequence[str] = (),
            no_key: bool = False,
        ) -> models.QuerySet[models.Model]:
            model = queryset.model
            lock_order.append(model.__name__)
            return original_select_for_update(
                queryset,
                nowait=nowait,
                skip_locked=skip_locked,
                of=of,
                no_key=no_key,
            )

        with patch("django.db.models.QuerySet.select_for_update", autospec=True, side_effect=observe_lock_order):
            validate_staged_execution_for_provisioning(str(advanced.execution_run_id), "modal")

        self.assertEqual(
            lock_order,
            ["Team", "Integration", "Task", "TaskRun", "TaskStagedRunTransition", "TaskRun", "TaskPublicationLease"],
        )

    def test_credential_free_workspace_uses_the_durable_lease_not_run_state(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        successor.state["credential_free_checkout"] = False
        successor.save(update_fields=["state"])

        workspace = resolve_credential_free_repository_workspace(str(successor.id), "modal")

        assert workspace is not None
        self.assertEqual(workspace.repository, "posthog/posthog")
        self.assertEqual(workspace.base_sha, "a" * 40)

    def test_credential_free_workspace_rejects_a_task_repository_binding_mismatch(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        Task.objects.filter(id=created.task_id).update(repository="attacker/repository")

        with self.assertRaisesRegex(TaskInvalidStateError, "staged_repository_binding_mismatch"):
            resolve_credential_free_repository_workspace(str(advanced.execution_run_id), "modal")

    @parameterized.expand(
        [
            ("transition_caller",),
            ("lease_caller",),
            ("lease_expired",),
        ]
    )
    def test_execution_provisioning_rejects_hostile_transition_or_lease_rows(self, mutation: str) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        if mutation == "transition_caller":
            TaskStagedRunTransition.objects.unscoped().filter(id=advanced.transition_id).update(caller_id=uuid.uuid4())
        elif mutation == "lease_caller":
            assert advanced.publication_lease_id is not None
            TaskPublicationLease.objects.unscoped().filter(id=advanced.publication_lease_id).update(
                caller_id=uuid.uuid4()
            )
        if mutation == "lease_expired":
            assert advanced.publication_lease_id is not None
            lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
            with (
                patch(
                    "products.tasks.backend.logic.services.staged_task_runs.django_timezone.now",
                    return_value=lease.expires_at + timedelta(seconds=1),
                ),
                self.assertRaises(TaskInvalidStateError),
            ):
                validate_staged_execution_for_provisioning(str(advanced.execution_run_id), "modal")
            lease.refresh_from_db()
            self.assertEqual(lease.status, TaskPublicationLease.Status.EXPIRED)
            return

        with self.assertRaises(TaskInvalidStateError):
            validate_staged_execution_for_provisioning(str(advanced.execution_run_id), "modal")

    def test_lease_expiry_is_capped_by_the_tasks_server_policy(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=replace(self._reservation(), expires_at=timezone.now() + timedelta(days=1)),
            )
        )

        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        self.assertLessEqual(lease.expires_at, timezone.now() + MAX_STAGED_PUBLICATION_LEASE_LIFETIME)
        self.assertLess(lease.starts_before, lease.expires_at)

    def test_publication_start_cutoff_rejects_new_reservations_and_bundle_uploads(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
                reservation=self._reservation(),
            )
        )
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)

        after_start_cutoff = lease.starts_before + timedelta(seconds=1)
        with (
            patch.object(staged_task_runs.django_timezone, "now", return_value=after_start_cutoff),
            self.assertRaisesRegex(TaskInvalidStateError, "publication_lease_start_cutoff"),
        ):
            staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))

        reservation = staged_task_runs.reserve_staged_draft_publication(str(advanced.execution_run_id))

        with (
            patch.object(staged_task_runs.django_timezone, "now", return_value=after_start_cutoff),
            self.assertRaisesRegex(TaskInvalidStateError, "publication_lease_start_cutoff"),
        ):
            staged_task_runs.record_staged_draft_publication_bundle(
                str(advanced.execution_run_id),
                storage_path=f"tasks/draft-publications/{reservation.publication_id}/{'c' * 64}.bundle",
                bundle_head_sha="b" * 40,
                bundle_sha256="c" * 64,
                bundle_byte_count=1024,
            )

    def test_publication_start_cutoff_must_be_between_creation_and_expiry(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        request = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=source.id,
            idempotency_key="proposal-1:execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read", "draft")),
            reservation=replace(self._reservation(), starts_before=timezone.now() - timedelta(seconds=1)),
        )

        with self.assertRaisesRegex(ValueError, "staged_task_reservation_start_cutoff"):
            tasks_api.advance_staged_task(request)

    def test_stale_run_reaping_revokes_staged_execution_capability(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=source.id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        with patch("products.tasks.backend.push_dispatcher.notify_task_run_failed"):
            self.assertTrue(tasks_api.claim_and_fail_stale_run(advanced.execution_run_id, "stale"))

        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        transition = TaskStagedRunTransition.objects.unscoped().get(id=advanced.transition_id)
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)

    def test_advance_retry_persists_server_detected_lease_expiry(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        request = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=source.id,
            idempotency_key="proposal-1:execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
            reservation=self._reservation(),
        )
        advanced = tasks_api.advance_staged_task(request)
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)

        with (
            patch(
                "products.tasks.backend.logic.services.staged_task_runs.django_timezone.now",
                return_value=lease.expires_at + timedelta(seconds=1),
            ),
            self.assertRaisesRegex(ValueError, "publication_lease_expired"),
        ):
            tasks_api.advance_staged_task(request)

        lease.refresh_from_db()
        self.assertEqual(lease.status, TaskPublicationLease.Status.EXPIRED)

    def test_cancellation_revokes_the_lease_once_without_reopening_it(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        revoke_input = RevokeStagedTaskCapabilitiesInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=created.task_id,
            source_run_id=created.analysis_run_id,
        )

        source.status = TaskRun.Status.CANCELLED
        source.save(update_fields=["status"])
        revoke_staged_capabilities_for_terminal_run(str(source.id))
        self.assertFalse(tasks_api.revoke_staged_task_capabilities(revoke_input).revoked)
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        transition = TaskStagedRunTransition.objects.unscoped().get(id=advanced.transition_id)
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)
        with self.assertRaisesRegex(ValueError, "staged_task_source_not_ready"):
            tasks_api.advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    task_id=created.task_id,
                    source_run_id=created.analysis_run_id,
                    idempotency_key="proposal-1:execution",
                    execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                    reservation=self._reservation(),
                )
            )

    @parameterized.expand(
        [
            ("failed_to_cancelled", TaskRun.Status.FAILED, TaskRun.Status.CANCELLED),
            ("cancelled_to_failed", TaskRun.Status.CANCELLED, TaskRun.Status.FAILED),
        ]
    )
    def test_opposite_terminal_status_still_revokes_staged_capability(
        self, _name: str, existing_status: str, requested_status: str
    ) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        source.status = existing_status
        source.save(update_fields=["status"])

        self.assertTrue(terminalize_staged_task_run(str(source.id), status=requested_status))

        source.refresh_from_db()
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        transition = TaskStagedRunTransition.objects.unscoped().get(id=advanced.transition_id)
        self.assertEqual(source.status, existing_status)
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)

    def test_execution_context_requires_the_stamped_manifest_and_modal_snapshot(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        advanced = tasks_api.advance_staged_task(
            AdvanceStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                task_id=created.task_id,
                source_run_id=created.analysis_run_id,
                idempotency_key="proposal-1:execution",
                execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
                reservation=self._reservation(),
            )
        )
        task = Task.objects.get(id=created.task_id)
        successor = TaskRun.objects.get(id=advanced.execution_run_id)

        _validate_staged_execution_context(task, successor, successor.state, "modal")
        with self.assertRaisesRegex(TaskInvalidStateError, "workspace_snapshot_unsupported"):
            _validate_staged_execution_context(task, successor, successor.state, "hogland")

    def test_legacy_run_state_skips_staged_validation(self) -> None:
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Existing interactive task",
            description="Existing workflow input remains unchanged.",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        run = TaskRun.objects.create(task=task, team=self.team, state={"mode": "interactive"})

        _validate_staged_execution_context(task, run, run.state, "hogland")

    def test_advance_rejects_cross_task_source_and_hogland_snapshot_backend(self) -> None:
        created = tasks_api.create_staged_task(self._create_input())
        source = TaskRun.objects.get(id=created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])
        other = tasks_api.create_staged_task(self._create_input(idempotency_key="pulse-run-2:implementation"))
        request = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=other.task_id,
            source_run_id=created.analysis_run_id,
            idempotency_key="proposal-1:execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
            reservation=self._reservation(),
        )

        with self.assertRaisesRegex(ValueError, "staged_task_identity_mismatch"):
            tasks_api.advance_staged_task(request)

        source.state["sandbox_backend"] = "hogland"
        source.save(update_fields=["state"])
        request = replace(request, task_id=created.task_id, idempotency_key="proposal-2:execution")
        with self.assertRaisesRegex(ValueError, "workspace_snapshot_unsupported"):
            tasks_api.advance_staged_task(request)


@override_settings(GITHUB_APP_SLUG="posthog")
class TestConcurrentStagedTaskAdvance(TransactionTestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Concurrent staged facade org")
        self.team = Team.objects.create(organization=self.organization, name="Concurrent staged facade team")
        self.user = User.objects.create(email="concurrent-staged-facade@example.com")
        self.caller_id = uuid.uuid4()
        self.github_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            integration_id="installation-1",
            config={"installation_id": "installation-1"},
            repository_cache=[
                {
                    "full_name": "posthog/posthog",
                    "can_push": True,
                    "private": True,
                    "visibility": "private",
                }
            ],
            errors="",
        )
        self.schedule = patch("products.tasks.backend.logic.services.staged_task_runs._schedule_staged_run")
        self.schedule.start()
        self.addCleanup(self.schedule.stop)
        self.created = tasks_api.create_staged_task(
            CreateStagedTaskInput(
                team_id=self.team.id,
                caller_id=self.caller_id,
                actor_id=self.user.id,
                idempotency_key="concurrent-staged-analysis",
                origin_product=Task.OriginProduct.WORKFLOW,
                title="Concurrent staged task",
                description="Concurrent staged task",
                repository="posthog/posthog",
                repository_grant=RepositoryGrantBindingDTO(
                    repository="posthog/posthog",
                    github_integration_id=self.github_integration.id,
                    github_installation_id="installation-1",
                    grant_version="1",
                ),
                repository_base=RepositoryBaseBindingDTO(
                    repository="posthog/posthog", base_sha="a" * 40, base_branch="main"
                ),
                analysis_manifest=CapabilityManifestDTO(version=1, phase="analysis", capabilities=("read",)),
            )
        )
        source = TaskRun.objects.get(id=self.created.analysis_run_id)
        source.state.update(snapshot_external_id="modal-analysis-snapshot", sandbox_backend="modal")
        source.save(update_fields=["state"])

    def _request(self) -> AdvanceStagedTaskInput:
        return AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            task_id=self.created.task_id,
            source_run_id=self.created.analysis_run_id,
            idempotency_key="concurrent-staged-execution",
            execution_manifest=CapabilityManifestDTO(version=1, phase="execution", capabilities=("read",)),
            reservation=PublicationLeaseReservationDTO(
                logical_artifact_key="concurrent-staged-artifact",
                action_key="concurrent-staged",
                repository="posthog/posthog",
                base_sha="a" * 40,
                base_branch="main",
                commit_message="Create draft",
                pr_title="Draft",
                pr_body="",
                github_integration_id=self.github_integration.id,
                github_installation_id="installation-1",
                grant_version="1",
                starts_before=timezone.now() + timedelta(minutes=4),
                expires_at=timezone.now() + timedelta(minutes=5),
            ),
        )

    def test_concurrent_advance_converges_on_one_successor_and_lease(self) -> None:
        request = self._request()
        barrier = Barrier(2)

        def advance() -> object:
            close_old_connections()
            try:
                barrier.wait()
                return tasks_api.advance_staged_task(request)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: advance(), range(2)))

        self.assertEqual(results[0], results[1])
        self.assertEqual(TaskRun.objects.filter(task_id=self.created.task_id).count(), 2)
        self.assertEqual(TaskPublicationLease.objects.unscoped().filter(task_id=self.created.task_id).count(), 1)

    @parameterized.expand([("owner_removal",), ("cancel_previous",), ("stale_reaper",)])
    def test_terminal_entrypoints_race_advance_retry_without_leaving_an_active_lease(self, kind: str) -> None:
        advanced = tasks_api.advance_staged_task(self._request())
        loop = Loop.objects.unscoped().create(
            team=self.team,
            created_by=self.user,
            name="Concurrent staged loop",
            instructions="Run",
            runtime_adapter="claude",
            model="claude-sonnet-5",
            enabled=True,
            overlap_policy=Loop.OverlapPolicy.SKIP if kind == "stale_reaper" else Loop.OverlapPolicy.CANCEL_PREVIOUS,
        )
        self.organization.members.add(self.user)
        task = Task.objects.get(id=self.created.task_id)
        task.origin_product = Task.OriginProduct.LOOP
        task.loop = loop
        task.save(update_fields=["origin_product", "loop", "updated_at"])
        source = TaskRun.objects.get(id=self.created.analysis_run_id)
        source.status = TaskRun.Status.COMPLETED
        source.save(update_fields=["status", "updated_at"])
        successor = TaskRun.objects.get(id=advanced.execution_run_id)
        successor.status = TaskRun.Status.IN_PROGRESS
        successor.state["loop_id"] = str(loop.id)
        successor.save(update_fields=["status", "state", "updated_at"])
        if kind == "owner_removal":
            new_owner = User.objects.create(email="replacement@example.com")
            self.organization.members.add(new_owner)
            loop.created_by = new_owner
            loop.save(update_fields=["created_by", "updated_at"])
        elif kind == "stale_reaper":
            TaskRun.objects.filter(id=successor.id).update(updated_at=timezone.now() - timedelta(hours=3))

        advance_holds_team_task = Event()
        release_advance = Event()
        terminalizer_at_team_lock = Event()
        advance_thread_ident: list[int] = []
        terminal_thread_ident: list[int] = []
        original_validate_task_identity = staged_task_runs._validate_task_identity
        original_team_select_for_update = Team.objects.select_for_update

        def hold_advance_after_team_and_task(task: Task, *, team_id: int, caller_id: str, idempotency_key: str) -> None:
            original_validate_task_identity(
                task,
                team_id=team_id,
                caller_id=caller_id,
                idempotency_key=idempotency_key,
            )
            if current_thread().ident == advance_thread_ident[0]:
                advance_holds_team_task.set()
                if not release_advance.wait(timeout=10):
                    raise TimeoutError("advance release was not signalled")

        def observe_terminal_team_lock(
            nowait: bool = False,
            skip_locked: bool = False,
            of: Sequence[str] = (),
            no_key: bool = False,
        ) -> models.QuerySet[Team]:
            queryset = original_team_select_for_update(
                nowait=nowait,
                skip_locked=skip_locked,
                of=of,
                no_key=no_key,
            )
            original_get = queryset.get

            def get(*get_args: object, **get_kwargs: object) -> object:
                if terminal_thread_ident and current_thread().ident == terminal_thread_ident[0]:
                    terminalizer_at_team_lock.set()
                return original_get(*get_args, **get_kwargs)

            wrapped_queryset = Mock(wraps=queryset)
            wrapped_queryset.get.side_effect = get
            return cast(models.QuerySet[Team], wrapped_queryset)

        def advance() -> object:
            close_old_connections()
            try:
                advance_thread_ident.append(current_thread().ident or 0)
                try:
                    return tasks_api.advance_staged_task(self._request())
                except ValueError as error:
                    if str(error) != "publication_lease_inactive":
                        raise
                    return error
            finally:
                close_old_connections()

        def terminalize() -> None:
            close_old_connections()
            try:
                terminal_thread_ident.append(current_thread().ident or 0)
                if kind == "owner_removal":
                    pause_loops_for_deactivated_user(self.user.id)
                else:
                    fire_loop(loop, None, f"race-{kind}", "ctx")
            finally:
                close_old_connections()

        with (
            patch("products.tasks.backend.loop_lifecycle.signal_loop_run_cancelled"),
            patch("products.tasks.backend.logic.services.loop_runs.signal_loop_run_cancelled"),
            patch.object(staged_task_runs, "_validate_task_identity", side_effect=hold_advance_after_team_and_task),
            patch.object(Team.objects, "select_for_update", side_effect=observe_terminal_team_lock),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            advance_future = executor.submit(advance)
            self.assertTrue(advance_holds_team_task.wait(timeout=10))
            terminal_future = executor.submit(terminalize)
            self.assertTrue(terminalizer_at_team_lock.wait(timeout=10))
            release_advance.set()
            advance_result = advance_future.result(timeout=30)
            terminal_future.result(timeout=30)

        self.assertFalse(isinstance(advance_result, OperationalError))
        self.assertTrue(
            advance_result == advanced
            or isinstance(advance_result, ValueError)
            and str(advance_result) == "publication_lease_inactive"
        )
        self.assertEqual(TaskRun.objects.filter(task_id=self.created.task_id).count(), 2)
        self.assertEqual(TaskPublicationLease.objects.unscoped().filter(task_id=self.created.task_id).count(), 1)
        successor.refresh_from_db()
        assert advanced.publication_lease_id is not None
        lease = TaskPublicationLease.objects.unscoped().get(id=advanced.publication_lease_id)
        transition = TaskStagedRunTransition.objects.unscoped().get(id=advanced.transition_id)
        self.assertIn(successor.status, (TaskRun.Status.CANCELLED, TaskRun.Status.FAILED))
        self.assertEqual(lease.status, TaskPublicationLease.Status.REVOKED)
        self.assertEqual(transition.status, TaskStagedRunTransition.Status.CANCELLED)
