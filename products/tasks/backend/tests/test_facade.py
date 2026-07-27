import importlib
from datetime import timedelta
from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Integration, Organization, Team
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, GitHubIntegration
from posthog.models.user import User

from products.tasks.backend.facade import (
    api as facade,
    contracts,
    warm as warm_facade,
)
from products.tasks.backend.logic.wizard_preflight import WizardRepositoryAccess, WizardRepositoryPreflight
from products.tasks.backend.models import SandboxCustomImage, SandboxEnvironment, Task, TaskRun
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PLACEHOLDER, build_wizard_pr_agent_prompt

_PREFLIGHT_UNKNOWN = WizardRepositoryPreflight(access=WizardRepositoryAccess.UNKNOWN)


def _repo_response(*, status_code: int = 200, default_branch: str = "main") -> MagicMock:
    return MagicMock(status_code=status_code, json=MagicMock(return_value={"default_branch": default_branch}))


def _tree_response(paths: list[str], *, status_code: int = 200, truncated: bool = False) -> MagicMock:
    payload = {"truncated": truncated, "tree": [{"type": "blob", "path": path} for path in paths]}
    return MagicMock(status_code=status_code, json=MagicMock(return_value=payload))


FACADE_MODULES = [
    "products.tasks.backend.facade.api",
    "products.tasks.backend.facade.contracts",
    "products.tasks.backend.facade.agents",
    "products.tasks.backend.facade.sandbox",
    "products.tasks.backend.facade.exceptions",
    "products.tasks.backend.facade.repo_selection",
    "products.tasks.backend.facade.streams",
    "products.tasks.backend.facade.temporal",
    "products.tasks.backend.facade.max_tools",
    "products.tasks.backend.facade.webhooks",
    "products.tasks.backend.facade.file_system",
]


class TestFacadeImports(TestCase):
    @parameterized.expand([(m,) for m in FACADE_MODULES])
    def test_module_imports_and_all_symbols_resolve(self, module_path):
        module = importlib.import_module(module_path)
        for symbol in getattr(module, "__all__", []):
            self.assertTrue(hasattr(module, symbol), f"{module_path} is missing exported symbol {symbol}")

    def test_enum_reexports_match_models(self):
        self.assertIs(facade.TaskRunStatus, TaskRun.Status)
        self.assertIs(facade.TaskRunEnvironment, TaskRun.Environment)
        self.assertIs(facade.TaskOriginProduct, Task.OriginProduct)
        self.assertIs(facade.SandboxNetworkAccessLevel, SandboxEnvironment.NetworkAccessLevel)


class TestFacadeReadsAndMappers(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create(email="facade@test.com", distinct_id="facade-distinct")

    def _make_task(self, **kwargs) -> Task:
        defaults = {
            "team": self.team,
            "title": "A task",
            "description": "desc",
            "origin_product": Task.OriginProduct.USER_CREATED,
            "created_by": self.user,
            "repository": "posthog/posthog",
        }
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def test_get_task_run_maps_all_fields(self):
        task = self._make_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            environment=TaskRun.Environment.CLOUD,
            output={"pr_url": "https://github.com/posthog/posthog/pull/1"},
            state={"mode": "interactive"},
        )

        dto = facade.get_task_run(run.id)
        assert dto is not None
        self.assertIsInstance(dto, contracts.TaskRunDTO)
        self.assertEqual(dto.id, run.id)
        self.assertEqual(dto.task_id, task.id)
        self.assertEqual(dto.team_id, self.team.id)
        self.assertEqual(dto.status, TaskRun.Status.COMPLETED.value)
        self.assertTrue(dto.is_terminal)
        self.assertEqual(dto.mode, "interactive")
        self.assertEqual(dto.workflow_id, run.workflow_id)
        self.assertEqual(dto.task_origin_product, Task.OriginProduct.USER_CREATED.value)
        self.assertEqual(dto.created_by_distinct_id, "facade-distinct")
        self.assertEqual(dto.pr_url, "https://github.com/posthog/posthog/pull/1")

    def test_get_task_run_team_scope(self):
        task = self._make_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        other_team = Team.objects.create(organization=self.organization, name="Other")

        self.assertIsNotNone(facade.get_task_run(run.id, team_id=self.team.id))
        self.assertIsNone(facade.get_task_run(run.id, team_id=other_team.id))
        self.assertIsNone(facade.get_task_run("00000000-0000-0000-0000-000000000000"))

    def test_task_exists_and_visibility(self):
        task = self._make_task()
        self.assertTrue(facade.task_exists(task.id, self.team.id))
        self.assertFalse(facade.task_exists(task.id, self.team.id + 999))
        # Creator can control it; an unrelated user cannot.
        self.assertTrue(facade.is_task_controllable_by_user(task.id, self.user.id))
        other_user = User.objects.create(email="other@test.com", distinct_id="other")
        self.assertFalse(facade.is_task_controllable_by_user(task.id, other_user.id))

    def _make_wizard_run(self, task: Task, status: TaskRun.Status, **kwargs) -> TaskRun:
        # A genuine server-started wizard run carries the markers create_wizard_cloud_run stamps:
        # a cloud environment and the (caller-unsettable) wizard_config state key.
        kwargs.setdefault("environment", TaskRun.Environment.CLOUD)
        kwargs.setdefault("state", {"wizard_config": {}})
        return TaskRun.objects.create(
            task=task,
            team=task.team,
            status=status,
            **kwargs,
        )

    def test_get_active_wizard_cloud_run_returns_latest_onboarding_run(self):
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        self._make_wizard_run(task, TaskRun.Status.QUEUED)
        latest = self._make_wizard_run(task, TaskRun.Status.IN_PROGRESS)

        run = facade.get_active_wizard_cloud_run(self.team.id)
        assert run is not None
        self.assertIsInstance(run, contracts.WizardCloudRunDTO)
        self.assertEqual(run.task_id, task.id)
        self.assertEqual(run.run_id, latest.id)
        self.assertEqual(run.status, TaskRun.Status.IN_PROGRESS.value)

    def test_get_active_wizard_cloud_run_ignores_non_onboarding_tasks(self):
        task = self._make_task(origin_product=Task.OriginProduct.USER_CREATED)
        self._make_wizard_run(task, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(facade.get_active_wizard_cloud_run(self.team.id))

    def test_get_active_wizard_cloud_run_ignores_user_created_run_without_wizard_markers(self):
        # A project member could create an onboarding task and bootstrap a cloud run through the
        # normal task APIs, but they can't set the protected wizard_config marker — so such a
        # planted run must never be surfaced to a provisioned teammate as the active wizard run.
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, environment=TaskRun.Environment.CLOUD
        )
        self.assertIsNone(facade.get_active_wizard_cloud_run(self.team.id))

        genuine = self._make_wizard_run(task, TaskRun.Status.IN_PROGRESS)
        run = facade.get_active_wizard_cloud_run(self.team.id)
        assert run is not None
        self.assertEqual(run.run_id, genuine.id)

    def test_get_active_wizard_cloud_run_ignores_local_run(self):
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        self._make_wizard_run(task, TaskRun.Status.IN_PROGRESS, environment=TaskRun.Environment.LOCAL)
        self.assertIsNone(facade.get_active_wizard_cloud_run(self.team.id))

    def test_get_active_wizard_cloud_run_surfaces_recently_completed_run(self):
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        run = self._make_wizard_run(task, TaskRun.Status.COMPLETED)
        handle = facade.get_active_wizard_cloud_run(self.team.id)
        assert handle is not None
        self.assertEqual(handle.run_id, run.id)

    def test_get_active_wizard_cloud_run_drops_stale_completed_run(self):
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        run = self._make_wizard_run(task, TaskRun.Status.COMPLETED)
        # auto_now fields can't be set on create — force them past the freshness window.
        stale = django_timezone.now() - timedelta(days=2)
        TaskRun.objects.filter(id=run.id).update(created_at=stale, updated_at=stale)
        self.assertIsNone(facade.get_active_wizard_cloud_run(self.team.id))

    def test_get_active_wizard_cloud_run_is_team_scoped(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        self._make_wizard_run(task, TaskRun.Status.IN_PROGRESS)
        self.assertIsNone(facade.get_active_wizard_cloud_run(other_team.id))

    def test_get_active_wizard_cloud_run_surfaces_older_active_run_behind_newer_stale_task(self):
        # The newest onboarding task's run is stale, but an older task still has a live run:
        # keying off task-recency alone would return nothing and hide the active run.
        older_task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        active = self._make_wizard_run(older_task, TaskRun.Status.IN_PROGRESS)
        newer_task = self._make_task(origin_product=Task.OriginProduct.ONBOARDING)
        stale_run = self._make_wizard_run(newer_task, TaskRun.Status.COMPLETED)
        now = django_timezone.now()
        TaskRun.objects.filter(id=active.id).update(
            created_at=now - timedelta(days=3), updated_at=now - timedelta(days=3)
        )
        TaskRun.objects.filter(id=stale_run.id).update(
            created_at=now - timedelta(days=2), updated_at=now - timedelta(days=2)
        )

        handle = facade.get_active_wizard_cloud_run(self.team.id)
        assert handle is not None
        self.assertEqual(handle.task_id, older_task.id)
        self.assertEqual(handle.run_id, active.id)

    def test_count_in_progress_runs_for_github_integration_scopes_to_live_runs_of_that_integration(self):
        integration = Integration.objects.create(team=self.team, kind="github", config={}, sensitive_config={})
        other_integration = Integration.objects.create(team=self.team, kind="github", config={}, sensitive_config={})

        live_task = self._make_task(github_integration=integration)
        TaskRun.objects.create(task=live_task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        TaskRun.objects.create(task=live_task, team=self.team, status=TaskRun.Status.COMPLETED)
        other_task = self._make_task(github_integration=other_integration)
        TaskRun.objects.create(task=other_task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        self.assertEqual(facade.count_in_progress_runs_for_github_integration(self.team.id, integration.id), 1)
        self.assertEqual(facade.count_in_progress_runs_for_github_integration(self.team.id + 999, integration.id), 0)

    def test_get_latest_pr_url_and_run_by_task(self):
        task = self._make_task()
        TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.COMPLETED, output={"pr_url": "https://x/pull/1"}
        )
        latest = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.COMPLETED, output={"pr_url": "https://x/pull/2"}
        )

        pr_urls = facade.get_latest_pr_url_by_task([task.id])
        self.assertEqual(pr_urls, {str(task.id): "https://x/pull/2"})

        latest_runs = facade.get_latest_run_by_task([task.id])
        self.assertEqual(latest_runs[str(task.id)].id, latest.id)

        self.assertEqual(facade.get_latest_pr_url_by_task([]), {})

    def test_get_conversation_task_dtos_carries_latest_run_id_not_nested_run(self):
        task = self._make_task(title="Conversation task")
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        latest = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        TaskRun.objects.create(task=task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        dtos = facade.get_conversation_task_dtos([task.id], self.team.id)

        self.assertEqual(set(dtos.keys()), {task.id})
        dto = dtos[task.id]
        self.assertIsInstance(dto, contracts.TaskDetailDTO)
        self.assertEqual(dto.id, task.id)
        self.assertEqual(dto.title, "Conversation task")
        # The nested run payload stays excluded (no presigned log URLs); only the id is carried.
        self.assertIsNone(dto.latest_run)
        self.assertEqual(dto.latest_run_id, latest.id)
        self.assertEqual(facade.get_conversation_task_dtos([task.id], other_team.id), {})

    def test_get_conversation_task_dtos_latest_run_id_none_without_runs(self):
        task = self._make_task(title="No runs")

        dto = facade.get_conversation_task_dtos([task.id], self.team.id)[task.id]

        self.assertIsNone(dto.latest_run_id)

    def test_get_conversation_task_dtos_is_cheap_for_many_tasks(self):
        tasks = [self._make_task(title=f"task-{i}") for i in range(5)]
        for task in tasks:
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        # A single query with the latest-run-id subquery — no per-task run lookup, no N+1.
        with self.assertNumQueries(1):
            dtos = facade.get_conversation_task_dtos([t.id for t in tasks], self.team.id)
            for task in tasks:
                self.assertIsNotNone(dtos[task.id].latest_run_id)

    @patch("products.tasks.backend.logic.services.warm.execute_task_processing_workflow")
    @patch("products.tasks.backend.logic.services.warm.is_team_limited", return_value=False)
    def test_warm_task_run_returns_contract(self, _mock_quota, mock_workflow):
        task = self._make_task(origin_product=Task.OriginProduct.POSTHOG_AI)

        with self.captureOnCommitCallbacks(execute=True):
            dto = warm_facade.warm_task_run(
                task.id,
                self.team.id,
                self.user.id,
                extra_state={"systemPrompt": {"type": "preset"}},
            )

        self.assertIsInstance(dto, contracts.WarmRunDTO)
        self.assertEqual(dto.task_id, task.id)
        self.assertTrue(dto.just_created)

        run = TaskRun.objects.get(id=dto.run_id)
        self.assertEqual(dto.run_status, run.status)
        self.assertEqual(run.state["systemPrompt"], {"type": "preset"})
        mock_workflow.assert_called_once()

    def test_stale_queued_and_fail(self):
        task = self._make_task()
        fresh = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        stale = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        stale_local = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.LOCAL
        )
        past = django_timezone.now() - timedelta(hours=48)
        TaskRun.objects.filter(pk__in=[stale.pk, stale_local.pk]).update(updated_at=past)

        stale_ids = facade.get_stale_queued_task_run_ids(older_than=timedelta(hours=24), limit=100)
        self.assertIn(stale.id, stale_ids)
        # Unfiltered, the query returns stale runs of every environment.
        self.assertIn(stale_local.id, stale_ids)
        self.assertNotIn(fresh.id, stale_ids)

        # The dispatch reconciler and the 24h fail sweep must never see local (desktop-driven)
        # runs — re-dispatching one starts a cloud workflow that hijacks the live local session,
        # and failing one turns an idle desktop session into a bogus failure.
        cloud_ids = facade.get_stale_queued_task_run_ids(
            older_than=timedelta(hours=24), limit=100, environment=TaskRun.Environment.CLOUD
        )
        self.assertIn(stale.id, cloud_ids)
        self.assertNotIn(stale_local.id, cloud_ids)

        local_ids = facade.get_stale_queued_task_run_ids(
            older_than=timedelta(hours=24), limit=100, environment=TaskRun.Environment.LOCAL
        )
        self.assertIn(stale_local.id, local_ids)
        self.assertNotIn(stale.id, local_ids)

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_failed"):
            self.assertTrue(facade.fail_task_run(stale.id, "boom"))
            # already-failed run is no longer QUEUED -> no-op
            self.assertFalse(facade.fail_task_run(stale.id, "boom again"))
        stale.refresh_from_db()
        self.assertEqual(stale.status, TaskRun.Status.FAILED.value)
        self.assertEqual(stale.error_message, "boom")

    def test_complete_idle_local_task_run_skips_run_handed_off_to_cloud(self):
        task = self._make_task()
        idle_local = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.LOCAL
        )
        # Between the janitor's candidate scan and the finalize call, a user can resume the run
        # into cloud (environment flips to CLOUD, workflow dispatched) — completing it then
        # would kill a just-started cloud run.
        handed_off = TaskRun.objects.create(
            task=task, team=self.team, status=TaskRun.Status.QUEUED, environment=TaskRun.Environment.CLOUD
        )

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_completed") as mock_notify:
            self.assertTrue(facade.complete_idle_local_task_run(idle_local.id))
            self.assertFalse(facade.complete_idle_local_task_run(handed_off.id))

        idle_local.refresh_from_db()
        self.assertEqual(idle_local.status, TaskRun.Status.COMPLETED.value)
        self.assertIsNone(idle_local.error_message)
        mock_notify.assert_not_called()
        handed_off.refresh_from_db()
        self.assertEqual(handed_off.status, TaskRun.Status.QUEUED.value)

    @parameterized.expand(
        [
            # A directory snapshot captured at a still-allowed path is carried into the new run.
            ("workspace_path", "/tmp/workspace", True),
            # A legacy "/tmp" capture is unusable (its content only fits that path, and mounting
            # over the live /tmp killed sandboxes) — resuming must drop it, not carry it forward
            # with the path stripped, or downstream defaulting would remount mismatched content.
            ("legacy_tmp_path", "/tmp", False),
        ]
    )
    def test_run_task_resume_carries_only_usable_directory_snapshots(
        self, _name: str, prior_mount_path: str, expect_carried: bool
    ):
        task = self._make_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "snapshot_external_id": "im-dir",
                "snapshot_kind": "directory",
                "snapshot_mount_path": prior_mount_path,
            },
        )

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow"):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "resume_from_run_id": str(previous_run.id)},
            )

        assert result is not None and result.error is None
        new_run = task.runs.exclude(id=previous_run.id).get()
        if expect_carried:
            self.assertEqual(new_run.state.get("snapshot_external_id"), "im-dir")
            self.assertEqual(new_run.state.get("snapshot_kind"), "directory")
            self.assertEqual(new_run.state.get("snapshot_mount_path"), prior_mount_path)
        else:
            self.assertNotIn("snapshot_external_id", new_run.state)
            self.assertNotIn("snapshot_kind", new_run.state)
            self.assertNotIn("snapshot_mount_path", new_run.state)

    @parameterized.expand(
        [
            ("ready", SandboxCustomImage.Status.READY, "posthog-sandbox-custom-1-abc:latest", True),
            ("not_ready", SandboxCustomImage.Status.BUILDING, "", False),
        ]
    )
    def test_run_task_resume_drops_carried_custom_image_when_not_ready(
        self, _name: str, status: str, modal_image_name: str, expect_carried: bool
    ):
        task = self._make_task()
        image = SandboxCustomImage(
            team=self.team,
            created_by=self.user,
            name="img",
            status=status,
            modal_image_name=modal_image_name,
        )
        image.save()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"custom_image_id": str(image.id)},
        )

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow"):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "resume_from_run_id": str(previous_run.id)},
            )

        assert result is not None and result.error is None
        new_run = task.runs.exclude(id=previous_run.id).get()
        if expect_carried:
            self.assertEqual(new_run.state.get("custom_image_id"), str(image.id))
        else:
            self.assertNotIn("custom_image_id", new_run.state)

    def test_stale_queued_created_at_hard_cap(self):
        task = self._make_task()
        now = django_timezone.now()
        ancient = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.filter(pk=ancient.pk).update(
            created_at=now - timedelta(hours=50), updated_at=now - timedelta(hours=2)
        )
        resuming = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.filter(pk=resuming.pk).update(
            created_at=now - timedelta(hours=50), updated_at=now - timedelta(minutes=10)
        )

        self.assertNotIn(ancient.id, facade.get_stale_queued_task_run_ids(older_than=timedelta(hours=24), limit=100))

        hard_capped = facade.get_stale_queued_task_run_ids(
            older_than=timedelta(hours=24), limit=100, created_hard_cap=timedelta(hours=48)
        )
        self.assertIn(ancient.id, hard_capped)
        self.assertNotIn(resuming.id, hard_capped)

    def test_update_task_run_state(self):
        task = self._make_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED, state={"mode": "bg"})
        new_state = facade.update_task_run_state(run.id, updates={"foo": "bar"}, remove_keys=["mode"])
        self.assertEqual(new_state.get("foo"), "bar")
        self.assertNotIn("mode", new_state)
        run.refresh_from_db()
        self.assertEqual(run.state.get("foo"), "bar")

    def test_collect_task_run_state_metrics(self):
        def collect():
            return facade.collect_task_run_state_metrics(
                open_statuses=["queued", "in_progress"],
                age_statuses=["queued", "in_progress"],
                terminal_statuses=["completed", "failed", "cancelled"],
                window_seconds=3600,
            )

        # These are global gauges (no team filter) bucketed by environment too, so other tests' rows can
        # share a (status, origin_product) key across environments. Measure the delta this test contributes
        # by summing matching rows across all environments, not an absolute count or a single bucket.
        def status_total(rows, status, origin_product):
            return sum(r.value for r in rows if r.status == status and r.origin_product == origin_product)

        queued = (TaskRun.Status.QUEUED.value, Task.OriginProduct.USER_CREATED.value)
        completed = (TaskRun.Status.COMPLETED.value, Task.OriginProduct.USER_CREATED.value)

        before = collect()
        created_before = sum(r.value for r in before.created_recently)
        queued_before = status_total(before.runs_in_status, *queued)
        terminal_before = status_total(before.terminal_recently, *completed)

        task = self._make_task()
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        metrics = collect()
        self.assertEqual(status_total(metrics.runs_in_status, *queued) - queued_before, 2)
        # COMPLETED is terminal, so it never appears in the open runs_in_status gauge
        self.assertNotIn(completed, {(r.status, r.origin_product) for r in metrics.runs_in_status})
        self.assertEqual(status_total(metrics.terminal_recently, *completed) - terminal_before, 1)
        self.assertEqual(sum(r.value for r in metrics.created_recently) - created_before, 3)
        self.assertTrue(all(r.value >= 0 for r in metrics.oldest_open_age_seconds))

    def test_upsert_internal_sandbox_env(self):
        env_id = facade.upsert_internal_sandbox_env(self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.TRUSTED)
        env = SandboxEnvironment.objects.get(id=env_id)
        self.assertFalse(env.private)
        self.assertTrue(env.internal)
        self.assertEqual(env.network_access_level, SandboxEnvironment.NetworkAccessLevel.TRUSTED.value)

        # Re-asserts policy and returns the same row.
        env.private = True
        env.save(update_fields=["private"])
        env_id_2 = facade.upsert_internal_sandbox_env(
            self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.TRUSTED
        )
        self.assertEqual(env_id_2, env_id)
        env.refresh_from_db()
        self.assertFalse(env.private)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_task_returns_contract(self, _mock_workflow):
        Integration.objects.create(team=self.team, kind="github", config={})
        created = facade.create_and_run_task(
            team=self.team,
            title="Created via facade",
            description="desc",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
        )
        self.assertIsInstance(created, contracts.CreatedTaskDTO)
        self.assertEqual(created.team_id, self.team.id)
        self.assertTrue(Task.objects.filter(id=created.task_id).exists())
        assert created.latest_run is not None
        self.assertEqual(created.latest_run.task_id, created.task_id)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_persists_dispatch_params_for_reconcile(self, _mock_workflow):
        # The reconciler re-dispatches lost runs from the row alone, so the dispatch params
        # must be committed onto the run — not left only in the in-memory on_commit closure.
        Integration.objects.create(team=self.team, kind="github", config={})
        created = facade.create_and_run_task(
            team=self.team,
            title="Created via facade",
            description="desc",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
            create_pr=False,
            posthog_mcp_scopes="full",
        )
        assert created.latest_run is not None
        run = TaskRun.objects.get(id=created.latest_run.id)
        self.assertEqual(run.state["pending_dispatch"]["create_pr"], False)
        self.assertEqual(run.state["pending_dispatch"]["posthog_mcp_scopes"], "full")
        self.assertEqual(run.state["pending_dispatch"]["user_id"], self.user.id)

    @patch("products.tasks.backend.facade.api.preflight_wizard_repository", return_value=_PREFLIGHT_UNKNOWN)
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_seeds_pending_user_message(self, _mock_workflow, _mock_preflight):
        Integration.objects.create(team=self.team, kind="github", config={})
        created = facade.create_wizard_cloud_run(
            team=self.team,
            user_id=self.user.id,
            repository="acme-co/web",
        )
        run = TaskRun.objects.get(task_id=created.task_id)
        # The agent server boots idle; forward_pending_user_message only kicks it off if the run state
        # carries the prompt. Without this the cloud wizard stalls right after "Started agent".
        head_branch = run.state.get("wizard_head_branch")
        # Server-generated head branch: the GitHub PR webhook binds the opened PR back to this
        # run by matching it (wizard PRs are bot-authored, so agent-side attribution can't).
        # Losing the state key or leaving the placeholder untemplated in the prompt silently
        # unbinds every wizard PR again.
        assert head_branch is not None
        self.assertRegex(head_branch, r"^posthog/instrumentation-[0-9a-f]{6}$")
        self.assertEqual(run.state.get("pending_user_message"), build_wizard_pr_agent_prompt(head_branch))
        self.assertIn(f"`{head_branch}`", run.state["pending_user_message"])
        self.assertNotIn(WIZARD_HEAD_BRANCH_PLACEHOLDER, run.state["pending_user_message"])
        # The agent-server self-delivers pending_user_message the moment it boots, so an
        # overlap-clone-boot launch (before run_wizard) burns the prompt on an untouched repo
        # and the run never opens a PR. Wizard runs must pin the overlap boot off.
        self.assertIs(run.state.get("overlap_clone_boot_enabled"), False)

    @parameterized.expand(
        [
            ("manifest_in_a_subdirectory", _repo_response(), _tree_response(["apps/web/package.json"]), None),
            (
                "repository_not_found",
                _repo_response(status_code=404),
                None,
                facade.WizardRepositoryInaccessibleError,
            ),
            (
                "no_project_manifest_anywhere",
                _repo_response(),
                _tree_response(["README.md", "docs/index.md"]),
                facade.WizardFrameworkUndetectableError,
            ),
            ("truncated_tree", _repo_response(), _tree_response(["README.md"], truncated=True), None),
            ("tree_read_raises", _repo_response(), RuntimeError("boom"), None),
            ("tree_read_non_200", _repo_response(), _tree_response([], status_code=500), None),
            ("repository_read_raises", RuntimeError("boom"), None, None),
            ("repository_read_non_200", _repo_response(status_code=500), None, None),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_preflight_only_blocks_on_unambiguous_answers(
        self, _name, repository_read, tree_read, expected_error, _mock_workflow
    ):
        # The pre-flight decides whether a run gets a sandbox at all, so it may reject only on an
        # answer that settles the question. Every degraded GitHub response has to create the run.
        Integration.objects.create(team=self.team, kind="github", config={})
        tasks_before = Task.objects.count()
        runs_before = TaskRun.objects.count()
        responses = [repository_read] if tree_read is None else [repository_read, tree_read]

        with patch.object(GitHubIntegration, "api_request", side_effect=responses):
            if expected_error is None:
                created = facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")
                self.assertTrue(TaskRun.objects.filter(task_id=created.task_id).exists())
                return
            with self.assertRaises(expected_error):
                facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")

        # A rejected kickoff must leave nothing behind: no task row, and no run holding a slot
        # against the user's quota.
        self.assertEqual(Task.objects.count(), tasks_before)
        self.assertEqual(TaskRun.objects.count(), runs_before)

    @parameterized.expand(
        [
            ("requested_branch", "develop", "develop"),
            ("default_branch", None, "trunk"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_preflight_reads_the_checked_out_ref(
        self, _name, branch, expected_ref, _mock_workflow
    ):
        # The sandbox checks out the requested branch; judging detectability on the default branch
        # instead would reject a run whose actual ref does hold a manifest.
        Integration.objects.create(team=self.team, kind="github", config={})
        with patch.object(
            GitHubIntegration,
            "api_request",
            side_effect=[_repo_response(default_branch="trunk"), _tree_response(["package.json"])],
        ) as api_request:
            facade.create_wizard_cloud_run(
                team=self.team, user_id=self.user.id, repository="acme-co/web", branch=branch
            )

        self.assertEqual(api_request.call_args_list[1].args[1], f"/repos/acme-co/web/git/trees/{expected_ref}")

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_preflight_skips_public_sandbox_repos(self, _mock_workflow):
        # The sandbox clones these unauthenticated and the task never binds an integration for
        # them, so reading them through the team's install answers a question the run never asks,
        # and a 404 from that install would block a run that would have worked.
        Integration.objects.create(team=self.team, kind="github", config={})

        with patch.object(GitHubIntegration, "api_request") as api_request:
            created = facade.create_wizard_cloud_run(
                team=self.team, user_id=self.user.id, repository="PostHog/hedgebox"
            )

        api_request.assert_not_called()
        self.assertTrue(TaskRun.objects.filter(task_id=created.task_id).exists())

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_preflight_reads_with_the_integration_the_task_binds(self, _mock_workflow):
        # An install whose token refresh is permanently failing is skipped when the task picks its
        # integration. The pre-flight has to skip it too: judging accessibility with credentials
        # the run never touches is exactly how a healthy repository gets falsely rejected.
        Integration.objects.create(team=self.team, kind="github", config={}, errors=ERROR_TOKEN_REFRESH_FAILED)
        usable = Integration.objects.create(team=self.team, kind="github", config={})
        read_by: list[int] = []

        def api_request(github, *args, **kwargs):
            read_by.append(github.integration.id)
            return _repo_response() if len(read_by) == 1 else _tree_response(["package.json"])

        with patch.object(GitHubIntegration, "api_request", autospec=True, side_effect=api_request):
            created = facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")

        self.assertEqual(set(read_by), {usable.id})
        self.assertEqual(Task.objects.get(id=created.task_id).github_integration_id, usable.id)


class TestRecentWizardCloudRunTimes(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    other_team: ClassVar[Team]
    user: ClassVar[User]
    other_user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Quota Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Quota Team")
        cls.other_team = Team.objects.create(organization=cls.organization, name="Other Quota Team")
        cls.user = User.objects.create(email="quota@test.com", distinct_id="quota-distinct")
        cls.other_user = User.objects.create(email="quota-other@test.com", distinct_id="quota-other-distinct")

    def _make_run(
        self,
        *,
        status=TaskRun.Status.IN_PROGRESS,
        origin_product=Task.OriginProduct.ONBOARDING,
        environment=TaskRun.Environment.CLOUD,
        state=None,
        team=None,
        created_by=None,
    ) -> TaskRun:
        task = Task.objects.create(
            team=team or self.team,
            title="Set up PostHog",
            description="wizard",
            origin_product=origin_product,
            created_by=created_by or self.user,
            repository="acme/app",
        )
        return TaskRun.objects.create(
            task=task,
            team=team or self.team,
            status=status,
            environment=environment,
            state={"wizard_config": {}} if state is None else state,
        )

    @parameterized.expand(
        [
            # Failed and cancelled runs must not consume quota: users retry exactly when a run broke.
            ("failed_run", {"status": TaskRun.Status.FAILED}, 0),
            ("cancelled_run", {"status": TaskRun.Status.CANCELLED}, 0),
            ("in_progress_run", {"status": TaskRun.Status.IN_PROGRESS}, 1),
            ("queued_run", {"status": TaskRun.Status.QUEUED}, 1),
            ("completed_run", {"status": TaskRun.Status.COMPLETED}, 1),
            # Only the PATCH-immutable wizard_config marker decides membership. Mutable fields
            # (environment, origin_product) must NOT be filtered, or a user could PATCH a run
            # to local and launder sandbox boots out of the quota.
            ("run_patched_to_local", {"environment": TaskRun.Environment.LOCAL}, 1),
            ("non_onboarding_task_with_marker", {"origin_product": Task.OriginProduct.USER_CREATED}, 1),
            ("run_without_wizard_config", {"state": {}}, 0),
        ]
    )
    def test_counts_only_quota_consuming_runs(self, _name, run_kwargs, expected_count):
        self._make_run(**run_kwargs)
        since = django_timezone.now() - timedelta(hours=1)
        self.assertEqual(len(facade.recent_wizard_cloud_run_times(self.user.id, since)), expected_count)

    def test_scopes_by_user_across_teams_and_respects_window(self):
        self._make_run()
        # Same user, different team: the throttle is per user, so this counts too.
        self._make_run(team=self.other_team)
        # Another user's run must never consume this user's quota.
        self._make_run(created_by=self.other_user)
        old_run = self._make_run()
        TaskRun.objects.filter(id=old_run.id).update(created_at=django_timezone.now() - timedelta(hours=3))

        since = django_timezone.now() - timedelta(hours=1)
        times = facade.recent_wizard_cloud_run_times(self.user.id, since)
        self.assertEqual(len(times), 2)
        self.assertEqual(times, sorted(times))
