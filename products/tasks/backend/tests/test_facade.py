import importlib
from datetime import timedelta
from typing import ClassVar

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.models import Integration, Organization, Team
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.user import User

from products.tasks.backend.facade import (
    api as facade,
    contracts,
    warm as warm_facade,
)
from products.tasks.backend.models import SandboxCustomImage, SandboxEnvironment, Task, TaskRun
from products.tasks.backend.prompts import WIZARD_HEAD_BRANCH_PLACEHOLDER, build_wizard_pr_agent_prompt

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
        # The unrestricted sweep (24h killer) still reaps abandoned local runs.
        self.assertIn(stale_local.id, stale_ids)
        self.assertNotIn(fresh.id, stale_ids)

        # The dispatch reconciler must never see local (desktop-driven) runs — re-dispatching
        # one starts a cloud workflow that hijacks and eventually fails the live local session.
        cloud_ids = facade.get_stale_queued_task_run_ids(older_than=timedelta(hours=24), limit=100, cloud_only=True)
        self.assertIn(stale.id, cloud_ids)
        self.assertNotIn(stale_local.id, cloud_ids)

        with patch("products.tasks.backend.push_dispatcher.notify_task_run_failed"):
            self.assertTrue(facade.fail_task_run(stale.id, "boom"))
            # already-failed run is no longer QUEUED -> no-op
            self.assertFalse(facade.fail_task_run(stale.id, "boom again"))
        stale.refresh_from_db()
        self.assertEqual(stale.status, TaskRun.Status.FAILED.value)
        self.assertEqual(stale.error_message, "boom")

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

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_seeds_pending_user_message(self, _mock_workflow):
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
            ("accessible", 200, True),
            ("inaccessible", 404, False),
            ("unknown_status", 502, True),
            ("probe_error", None, True),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_probes_repository_access(self, _name, probe_status, run_created, _mock_workflow):
        # The probe must block only a confirmed-inaccessible repo (the sandbox clone would
        # fail after a full boot) and fail open on any indeterminate GitHub answer.
        Integration.objects.create(team=self.team, kind="github", config={})
        tasks_before = Task.objects.count()
        if probe_status is None:
            probe = patch.object(GitHubIntegration, "api_request", side_effect=GitHubIntegrationError("boom"))
        else:
            probe = patch.object(GitHubIntegration, "api_request", return_value=MagicMock(status_code=probe_status))
        with probe:
            if run_created:
                created = facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")
                self.assertTrue(TaskRun.objects.filter(task_id=created.task_id).exists())
            else:
                with self.assertRaises(facade.WizardRepositoryInaccessibleError):
                    facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")
                self.assertEqual(Task.objects.count(), tasks_before)
                self.assertFalse(TaskRun.objects.exists())

    @parameterized.expand(
        [
            ("manifest_present", [{"name": "package.json"}, {"name": "README.md"}], True),
            ("no_root_manifest", [{"name": "README.md"}, {"name": "docs"}], False),
            ("listing_error", GitHubIntegrationError("boom"), True),
            ("listing_non_200", None, True),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_framework_detectability_preflight(
        self, _name, listing, run_created, _mock_workflow
    ):
        # Blocking must require a *successful* root listing with no supported manifest —
        # the deterministic "Could not auto-detect your framework" sandbox failure. Any
        # listing uncertainty has to fail open.
        Integration.objects.create(team=self.team, kind="github", config={})
        tasks_before = Task.objects.count()
        metadata_response = MagicMock(status_code=200)
        if isinstance(listing, Exception):
            contents_effect = listing
        elif listing is None:
            contents_effect = MagicMock(status_code=500)
        else:
            contents_effect = MagicMock(status_code=200, json=MagicMock(return_value=listing))
        with patch.object(GitHubIntegration, "api_request", side_effect=[metadata_response, contents_effect]):
            if run_created:
                created = facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")
                self.assertTrue(TaskRun.objects.filter(task_id=created.task_id).exists())
            else:
                with self.assertRaises(facade.WizardFrameworkUndetectableError):
                    facade.create_wizard_cloud_run(team=self.team, user_id=self.user.id, repository="acme-co/web")
                self.assertEqual(Task.objects.count(), tasks_before)
                self.assertFalse(TaskRun.objects.exists())
