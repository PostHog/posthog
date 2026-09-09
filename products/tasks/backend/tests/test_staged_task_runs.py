from uuid import uuid4

import pytest

from django.test import TestCase
from django.utils import timezone

from posthog.models import Organization, OrganizationMembership, Team
from posthog.models.integration import Integration
from posthog.models.user import User

from products.tasks.backend.facade.staged_execution import (
    AdvanceStagedTaskInput,
    CreateStagedTaskInput,
    InvalidStagedTaskBindingError,
    StagedCapabilityManifest,
    StagedRepositoryBinding,
    advance_staged_task,
    cancel_staged_task,
    create_staged_task,
)
from products.tasks.backend.models import Task, TaskRun, TaskStagedRun, TaskWorkflowDispatch


class TestStagedTaskRuns(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Staged tasks org")
        self.team = Team.objects.create(organization=self.organization, name="Staged tasks team")
        self.other_team = Team.objects.create(organization=self.organization, name="Other staged tasks team")
        self.user = User.objects.create(email="staged-tasks@example.com")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.caller_id = uuid4()

    def _analysis_manifest(self) -> StagedCapabilityManifest:
        return StagedCapabilityManifest(
            version=1,
            phase="analysis",
            mcp_scope_preset="read_only",
            disabled_tools=("WebFetch", "WebSearch"),
        )

    def _execution_manifest(self) -> StagedCapabilityManifest:
        return StagedCapabilityManifest(
            version=1,
            phase="execution",
            mcp_scope_preset="full",
            disabled_tools=("WebFetch",),
        )

    def _create_input(self, *, idempotency_key: str = "create-key") -> CreateStagedTaskInput:
        return CreateStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            actor_id=self.user.id,
            idempotency_key=idempotency_key,
            origin_product="task_analysis",
            title="Review the weekly signal",
            description="Identify whether the signal needs an execution follow-up.",
            analysis_manifest=self._analysis_manifest(),
            repository=None,
            output_schema=None,
        )

    def test_create_replays_the_same_analysis_task_for_one_caller_key(self) -> None:
        """Break caught: dropping the lifecycle idempotency guard creates duplicate analysis work."""
        first = create_staged_task(self._create_input())
        second = create_staged_task(self._create_input())

        assert first == second
        assert Task.objects.filter(team=self.team).count() == 1
        assert TaskRun.objects.filter(team=self.team).count() == 1
        assert TaskStagedRun.objects.for_team(self.team.id).filter(caller_id=self.caller_id).count() == 1

    def test_advance_rejects_a_staged_run_outside_the_callers_team(self) -> None:
        """Break caught: a caller can create an execution run for another team's staged task."""
        created = create_staged_task(self._create_input())

        with pytest.raises(InvalidStagedTaskBindingError):
            advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.other_team.id,
                    caller_id=self.caller_id,
                    staged_run_id=created.staged_run_id,
                    idempotency_key="advance-key",
                    execution_manifest=self._execution_manifest(),
                )
            )

        assert TaskRun.objects.filter(task_id=created.task_id).count() == 1

    def test_advance_replay_reuses_one_execution_run(self) -> None:
        """Break caught: an advance replay creates a second successor run."""
        created = create_staged_task(self._create_input())
        TaskRun.objects.filter(id=created.analysis_run_id).update(
            status=TaskRun.Status.COMPLETED,
            state={"snapshot_external_id": "snapshot-1", "snapshot_kind": "filesystem"},
        )
        advance_input = AdvanceStagedTaskInput(
            team_id=self.team.id,
            caller_id=self.caller_id,
            staged_run_id=created.staged_run_id,
            idempotency_key="advance-key",
            execution_manifest=self._execution_manifest(),
        )

        results = [advance_staged_task(advance_input), advance_staged_task(advance_input)]

        assert results[0] == results[1]
        assert TaskStagedRun.objects.for_team(self.team.id).filter(id=created.staged_run_id).count() == 1
        assert TaskRun.objects.filter(task_id=created.task_id).count() == 2
        execution_run = TaskRun.objects.get(id=results[0].execution_run_id)
        assert execution_run.state["snapshot_external_id"] == "snapshot-1"
        assert execution_run.state["resume_from_run_id"] == str(created.analysis_run_id)

    def test_advance_rejects_an_analysis_manifest(self) -> None:
        """Break caught: an analysis capability set can be used to authorize execution."""
        created = create_staged_task(self._create_input())
        TaskRun.objects.filter(id=created.analysis_run_id).update(
            status=TaskRun.Status.COMPLETED,
            state={"snapshot_external_id": "snapshot-1", "snapshot_kind": "filesystem"},
        )

        with pytest.raises(ValueError, match="execution"):
            advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    staged_run_id=created.staged_run_id,
                    idempotency_key="advance-key",
                    execution_manifest=self._analysis_manifest(),
                )
            )

        assert TaskRun.objects.filter(task_id=created.task_id).count() == 1

    def test_create_rejects_a_repository_binding_for_another_installation(self) -> None:
        """Break caught: a protected repository grant can be paired with another installation."""
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            config={"installation_id": "bound-installation"},
            repository_cache=[{"id": 1, "name": "posthog", "full_name": "posthog/posthog"}],
            repository_cache_updated_at=timezone.now(),
        )
        input = self._create_input()
        input = CreateStagedTaskInput(
            **{
                **input.__dict__,
                "repository": StagedRepositoryBinding(
                    repository="posthog/posthog",
                    base_sha="a" * 40,
                    base_branch="master",
                    github_integration_id=integration.id,
                    github_installation_id="different-installation",
                    grant_version="v1",
                ),
            }
        )

        with pytest.raises(InvalidStagedTaskBindingError):
            create_staged_task(input)

    def test_create_rejects_malformed_repository_paths_and_mutable_revisions(self) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            config={"installation_id": "bound-installation"},
        )
        for repository, base_sha in [
            ("../repo", "a" * 40),
            ("owner/repo/extra", "a" * 40),
            ("owner/..", "a" * 40),
            ("owner/repo", "main"),
        ]:
            input = self._create_input()
            with pytest.raises(ValueError):
                create_staged_task(
                    CreateStagedTaskInput(
                        **{
                            **input.__dict__,
                            "repository": StagedRepositoryBinding(
                                repository=repository,
                                base_sha=base_sha,
                                base_branch="master",
                                github_integration_id=integration.id,
                                github_installation_id="bound-installation",
                                grant_version="v1",
                            ),
                        }
                    )
                )

    def test_create_rejects_repository_missing_from_the_active_installation_cache(self) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB,
            config={"installation_id": "bound-installation"},
            repository_cache=[{"id": 1, "name": "other", "full_name": "owner/other"}],
            repository_cache_updated_at=timezone.now(),
        )
        input = self._create_input()

        with pytest.raises(InvalidStagedTaskBindingError):
            create_staged_task(
                CreateStagedTaskInput(
                    **{
                        **input.__dict__,
                        "repository": StagedRepositoryBinding(
                            repository="owner/repo",
                            base_sha="a" * 40,
                            base_branch="master",
                            github_integration_id=integration.id,
                            github_installation_id="bound-installation",
                            grant_version="v1",
                        ),
                    }
                )
            )

    def test_advance_rejects_a_deactivated_actor_without_creating_successor_work(self) -> None:
        created = create_staged_task(self._create_input())
        TaskRun.objects.filter(id=created.analysis_run_id).update(
            status=TaskRun.Status.COMPLETED,
            state={"snapshot_external_id": "snapshot-1", "snapshot_kind": "filesystem"},
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        with pytest.raises(InvalidStagedTaskBindingError):
            advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    staged_run_id=created.staged_run_id,
                    idempotency_key="advance-key",
                    execution_manifest=self._execution_manifest(),
                )
            )

        assert TaskRun.objects.filter(task_id=created.task_id).count() == 1
        assert (
            TaskWorkflowDispatch.objects.for_team(self.team.id).filter(task_run__task_id=created.task_id).count() == 1
        )

    def test_cancelled_staged_run_cannot_advance(self) -> None:
        created = create_staged_task(self._create_input())
        TaskRun.objects.filter(id=created.analysis_run_id).update(
            status=TaskRun.Status.COMPLETED,
            state={"snapshot_external_id": "snapshot-1", "snapshot_kind": "filesystem"},
        )
        assert cancel_staged_task(team_id=self.team.id, caller_id=self.caller_id, staged_run_id=created.staged_run_id)
        with pytest.raises(InvalidStagedTaskBindingError):
            advance_staged_task(
                AdvanceStagedTaskInput(
                    team_id=self.team.id,
                    caller_id=self.caller_id,
                    staged_run_id=created.staged_run_id,
                    idempotency_key="advance-key",
                    execution_manifest=self._execution_manifest(),
                )
            )
        assert TaskRun.objects.filter(task_id=created.task_id).count() == 1
