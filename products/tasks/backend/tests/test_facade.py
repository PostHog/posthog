import importlib
import threading
from datetime import timedelta
from typing import Any, ClassVar
from uuid import UUID, uuid4

from unittest.mock import MagicMock, patch

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone as django_timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Integration, Organization, OrganizationMembership, Team
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.models import SignalTeamConfig
from products.tasks.backend.facade import (
    api as facade,
    contracts,
    warm as warm_facade,
)
from products.tasks.backend.models import (
    TASK_OWNERSHIP_VERSION_STATE_KEY,
    Channel,
    SandboxCustomImage,
    SandboxEnvironment,
    Task,
    TaskRun,
    TaskWorkflowDispatch,
)
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


class TestTaskHandoffConcurrency(TransactionTestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.owner = User.objects.create_user(email="owner@example.com", first_name="Owner", password="password")
        self.recipient = User.objects.create_user(
            email="recipient@example.com", first_name="Recipient", password="password"
        )
        self.organization.members.add(self.owner, self.recipient)
        self.task = Task.objects.create(
            team=self.team,
            title="Race task",
            description="Run later",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.owner,
        )

    def test_delayed_bootstrap_cannot_create_run_after_handoff(self) -> None:
        create_reached = threading.Event()
        handoff_finished = threading.Event()
        results: list[contracts.TaskRunCreateResult | None] = []
        errors: list[BaseException] = []
        original_create_run = Task.create_run

        def delayed_create_run(
            task: Task,
            environment: TaskRun.Environment | None = None,
            mode: str = "background",
            extra_state: dict | None = None,
            branch: str | None = None,
        ) -> TaskRun:
            create_reached.set()
            if not handoff_finished.wait(timeout=10):
                raise TimeoutError("handoff did not finish")
            return original_create_run(
                task,
                environment=environment,
                mode=mode,
                extra_state=extra_state,
                branch=branch,
            )

        def bootstrap() -> None:
            close_old_connections()
            try:
                results.append(facade.bootstrap_task_run(self.task.id, self.team.id, self.owner.id, validated_data={}))
            except BaseException as error:
                errors.append(error)
            finally:
                close_old_connections()

        with patch.object(Task, "create_run", new=delayed_create_run):
            thread = threading.Thread(target=bootstrap)
            thread.start()
            self.assertTrue(create_reached.wait(timeout=10))
            handoff = facade.handoff_task(
                self.task.id,
                self.team.id,
                self.owner.id,
                target_user_id=self.recipient.id,
            )
            handoff_finished.set()
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIsNotNone(handoff)
        self.assertEqual(results, [None])
        self.assertFalse(TaskRun.objects.filter(task=self.task).exists())

    def test_handoff_waits_for_in_flight_task_update(self) -> None:
        update_at_save = threading.Event()
        allow_update_save = threading.Event()
        update_saved = threading.Event()
        handoff_finished = threading.Event()
        errors: list[BaseException] = []
        original_save = Task.save

        def delayed_save(task: Task, *args: Any, **kwargs: Any) -> None:
            if task.id == self.task.id and task.title == "Updated title" and not update_saved.is_set():
                update_at_save.set()
                if not allow_update_save.wait(timeout=10):
                    raise TimeoutError("update save was not released")
                result = original_save(task, *args, **kwargs)
                update_saved.set()
                return result
            return original_save(task, *args, **kwargs)

        def update() -> None:
            close_old_connections()
            try:
                facade.update_task(
                    self.task.id,
                    self.team.id,
                    self.owner.id,
                    validated_data={"title": "Updated title"},
                )
            except BaseException as error:
                errors.append(error)
            finally:
                close_old_connections()

        def handoff() -> None:
            close_old_connections()
            try:
                facade.handoff_task(
                    self.task.id,
                    self.team.id,
                    self.owner.id,
                    target_user_id=self.recipient.id,
                )
            except BaseException as error:
                errors.append(error)
            finally:
                handoff_finished.set()
                close_old_connections()

        with patch.object(Task, "save", new=delayed_save):
            update_thread = threading.Thread(target=update)
            update_thread.start()
            self.assertTrue(update_at_save.wait(timeout=10))
            handoff_thread = threading.Thread(target=handoff)
            handoff_thread.start()
            self.assertFalse(handoff_finished.wait(timeout=1))
            allow_update_save.set()
            update_thread.join(timeout=10)
            handoff_thread.join(timeout=10)

        self.assertFalse(update_thread.is_alive())
        self.assertFalse(handoff_thread.is_alive())
        self.assertEqual(errors, [])
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Updated title")
        self.assertEqual(self.task.created_by_id, self.recipient.id)


class TestBootstrapTaskRun(TestCase):
    def test_invalid_cloud_origin_returns_validation_error(self) -> None:
        organization = Organization.objects.create(name="Legacy task org")
        team = Team.objects.create(organization=organization, name="Legacy task team")
        user = User.objects.create(email="legacy-task@example.com")
        task = Task.objects.create(
            team=team,
            created_by=user,
            title="Legacy task",
            description="Run later",
            origin_product="automation",
        )

        result = facade.bootstrap_task_run(
            task.id,
            team.id,
            user.id,
            validated_data={"environment": TaskRun.Environment.CLOUD},
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result.error,
            contracts.TaskRunValidationError(
                kind="validation_error",
                code="invalid_input",
                detail="This task uses an unsupported origin. Start it locally or create a new task to run it in the cloud.",
                attr="origin_product",
            ),
        )
        self.assertFalse(TaskRun.objects.filter(task=task).exists())


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

    @parameterized.expand([("the_sandbox", True), ("a_human_reader", False)])
    def test_run_detail_serves_the_boot_prompt_to_the_sandbox_only(self, _name, include_agent_state):
        # The agent reads initial_prompt_override off this payload to build its first
        # message; dropping it strips it silently and the run falls back to
        # task.description. But it embeds the triggering event wholesale (for a Slack
        # trigger, a private channel's content) and workflow tasks are team-readable,
        # so human readers must not receive it.
        task = self._make_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            state={"initial_prompt_override": "framed prompt", "sandbox_jwt_kid": "secret"},
        )

        detail = facade.get_task_run_detail(run.id, task.id, self.team.id, include_agent_state=include_agent_state)

        assert detail is not None
        expected = "framed prompt" if include_agent_state else None
        assert detail.state.get("initial_prompt_override") == expected
        assert "sandbox_jwt_kid" not in detail.state

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

    def test_resume_in_cloud_rejects_run_from_previous_owner(self):
        task = self._make_task(state={TASK_OWNERSHIP_VERSION_STATE_KEY: "current-version"})
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED, state={})

        outcome, resumed_run, _ = facade.resume_task_run_in_cloud(
            run.id,
            task.id,
            self.team.id,
            self.user.id,
        )

        self.assertEqual(outcome, "ownership_changed")
        self.assertIsNone(resumed_run)

    def test_resume_in_cloud_rejects_invalid_origin(self):
        task = self._make_task(origin_product="automation")
        run = task.create_run(environment=TaskRun.Environment.LOCAL)

        outcome, resumed_run, _ = facade.resume_task_run_in_cloud(
            run.id,
            task.id,
            self.team.id,
            self.user.id,
        )

        self.assertEqual(outcome, "invalid_origin")
        self.assertIsNone(resumed_run)
        run.refresh_from_db()
        self.assertEqual(run.environment, TaskRun.Environment.LOCAL)

    def test_task_exists_and_visibility(self):
        task = self._make_task()
        self.assertTrue(facade.task_exists(task.id, self.team.id))
        self.assertFalse(facade.task_exists(task.id, self.team.id + 999))
        # Creator can control it; an unrelated user cannot.
        self.assertTrue(facade.is_task_controllable_by_user(task.id, self.user.id))
        other_user = User.objects.create(email="other@test.com", distinct_id="other")
        self.assertFalse(facade.is_task_controllable_by_user(task.id, other_user.id))

    def test_task_control_runtime_and_origin_uses_control_predicate(self):
        task = self._make_task(origin_product=Task.OriginProduct.POSTHOG_AI, runtime=Task.Runtime.PI)
        self.assertEqual(
            facade.task_control_runtime_and_origin(task.id, self.team.id, self.user.id),
            facade.ControlVisibleTask(
                runtime=Task.Runtime.PI.value, origin_product=Task.OriginProduct.POSTHOG_AI.value
            ),
        )

        # An experiments task is readable across the team but only its creator may drive it, so the
        # warm gate must use the control predicate, not the read predicate.
        other_user = User.objects.create(email="control-origin@test.com", distinct_id="control-origin")
        experiments_task = self._make_task(origin_product=Task.OriginProduct.EXPERIMENTS)
        self.assertIsNotNone(facade.get_task_detail(experiments_task.id, self.team.id, other_user.id))
        self.assertIsNone(facade.task_control_runtime_and_origin(experiments_task.id, self.team.id, other_user.id))

        self.assertIsNone(facade.task_control_runtime_and_origin(uuid4(), self.team.id, self.user.id))

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

        dtos = facade.get_conversation_task_dtos([task.id], self.team.id, self.user.id)

        self.assertEqual(set(dtos.keys()), {task.id})
        dto = dtos[task.id]
        self.assertIsInstance(dto, contracts.TaskDetailDTO)
        self.assertEqual(dto.id, task.id)
        self.assertEqual(dto.title, "Conversation task")
        # The nested run payload stays excluded (no presigned log URLs); only the id is carried.
        self.assertIsNone(dto.latest_run)
        self.assertEqual(dto.latest_run_id, latest.id)
        self.assertEqual(facade.get_conversation_task_dtos([task.id], other_team.id, self.user.id), {})

    def test_get_conversation_task_dtos_latest_run_id_none_without_runs(self):
        task = self._make_task(title="No runs")

        dto = facade.get_conversation_task_dtos([task.id], self.team.id, self.user.id)[task.id]

        self.assertIsNone(dto.latest_run_id)

    def test_get_conversation_task_dtos_excludes_soft_deleted_task(self):
        task = self._make_task(title="Deleted conversation task")
        task.soft_delete()

        self.assertEqual(facade.get_conversation_task_dtos([task.id], self.team.id, self.user.id), {})

    def test_get_conversation_task_dtos_is_cheap_for_many_tasks(self):
        tasks = [self._make_task(title=f"task-{i}") for i in range(5)]
        for task in tasks:
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        # A single query with the latest-run-id subquery — no per-task run lookup, no N+1.
        with self.assertNumQueries(1):
            dtos = facade.get_conversation_task_dtos([t.id for t in tasks], self.team.id, self.user.id)
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

    def test_run_task_resume_exposes_pending_prompt_to_agent(self):
        task = self._make_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
        )

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow"):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "resume_from_run_id": str(previous_run.id),
                    "pending_user_message": "Continue with the refactor",
                    "pending_user_artifact_ids": [],
                },
            )

        assert result is not None and result.error is None
        new_run = task.runs.exclude(id=previous_run.id).get()
        detail = facade.get_task_run_detail(new_run.id, task.id, self.team.id)
        assert detail is not None
        self.assertEqual(detail.state["pending_user_message"], "Continue with the refactor")

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

    def test_run_task_resume_carries_self_driving_head_branch(self):
        # The signals review carve-out binds a PR to its run by matching the PR head ref against the
        # PATCH-protected state.self_driving_head_branch stamp. A resume mints a new run, so the
        # stamp must be copied forward or the carve-out stops matching the successor — the receiver
        # leg refuses on the run-id mismatch and the webhook leg drops a cancelled predecessor — which
        # silently ends re-reviews after the usual resume-after-cancel. Mirrors the wizard_head_branch
        # carry that sits beside it.
        task = self._make_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"self_driving_head_branch": "posthog-self-driving/fix-abc123"},
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
        self.assertEqual(new_run.state.get("self_driving_head_branch"), "posthog-self-driving/fix-abc123")

    @parameterized.expand(
        [
            # The inbox "Create PR" button sends no branch, so the team's configured base branch is
            # the only thing that can keep the PR off the repo's GitHub default branch. Repo casing
            # differs from the stored key because GitHub preserves it while the serializer lowercases.
            ("configured_branch_applied", {"acme/web": "dev"}, {}, "dev"),
            # A caller that picked a branch already decided; re-resolving would discard that choice.
            ("explicit_branch_wins", {"acme/web": "dev"}, {"branch": "hotfix"}, "hotfix"),
            # Another repo's entry must never be borrowed, because that lands the PR on a
            # branch belonging to a different repository.
            ("other_repo_not_borrowed", {"acme/api": "staging"}, {}, None),
        ]
    )
    def test_run_task_applies_configured_base_branch(
        self, _name: str, overrides: dict, extra_validated_data: dict, expected_branch: str | None
    ):
        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"autostart_base_branches": overrides})
        task = self._make_task(repository="Acme/Web", origin_product=Task.OriginProduct.SIGNAL_REPORT)

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow"):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "run_source": "signal_report", **extra_validated_data},
            )

        assert result is not None and result.error is None
        run = task.runs.get()
        self.assertEqual(run.branch, expected_branch)
        self.assertEqual((run.state or {}).get("pr_base_branch"), expected_branch)

    def test_run_task_leaves_branch_unset_for_user_created_tasks(self):
        # The override is scoped to self-driving tasks. A user-created task keeps targeting the repo
        # default, so broadening the resolution would silently redirect unrelated task runs.
        SignalTeamConfig.objects.update_or_create(
            team=self.team, defaults={"autostart_base_branches": {"acme/web": "dev"}}
        )
        task = self._make_task(repository="Acme/Web", origin_product=Task.OriginProduct.USER_CREATED)

        with patch("products.tasks.backend.facade.api._trigger_task_processing_workflow"):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "run_source": "signal_report"},
            )

        assert result is not None and result.error is None
        self.assertIsNone(task.runs.get().branch)

    def test_run_task_returns_validation_error_for_invalid_cloud_origin(self):
        task = self._make_task(origin_product="automation")

        result = facade.run_task(task.id, self.team.id, self.user.id, validated_data={})

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result.error,
            contracts.TaskValidationError(
                kind="validation_error",
                code="invalid_input",
                detail="This task uses an unsupported origin. Start it locally or create a new task to run it in the cloud.",
                attr="origin_product",
            ),
        )
        self.assertFalse(TaskRun.objects.filter(task=task).exists())

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

    def test_cloud_sweep_guard_uses_dispatch_enqueue_time(self):
        task = self._make_task()
        now = django_timezone.now()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            environment=TaskRun.Environment.CLOUD,
        )
        TaskRun.objects.filter(pk=run.pk).update(
            created_at=now - timedelta(hours=50), updated_at=now - timedelta(hours=2)
        )
        dispatch = TaskWorkflowDispatch.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=run,
            workflow_id=run.workflow_id,
            dispatch_kind=TaskWorkflowDispatch.Kind.RESTART,
            payload={},
            enqueued_at=now - timedelta(minutes=5),
        )
        TaskWorkflowDispatch.objects.for_team(self.team.id).filter(pk=dispatch.pk).update(
            created_at=now - timedelta(hours=50)
        )

        stale_ids = facade.get_stale_queued_task_run_ids(
            older_than=timedelta(hours=24),
            limit=100,
            created_hard_cap=timedelta(hours=48),
            environment=TaskRun.Environment.CLOUD,
        )

        self.assertNotIn(run.id, stale_ids)

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

    def test_upsert_internal_sandbox_env_never_adopts_user_created_row(self):
        # Users can create environments with arbitrary names through the sandbox environment
        # API. Adopting a same-named user row would carry its custom image / env vars into an
        # internal run holding the run's tokens — so provisioning must create its own internal
        # row alongside and leave the user's row untouched (not deleted, not converted).
        user_env = SandboxEnvironment.objects.create(
            team=self.team,
            name="SIGNALS_X",
            internal=False,
            environment_variables={"EXFIL_TARGET": "https://attacker.example"},
        )

        env_id = facade.upsert_internal_sandbox_env(self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.FULL)

        self.assertNotEqual(str(env_id), str(user_env.id))
        env = SandboxEnvironment.objects.get(id=env_id)
        self.assertTrue(env.internal)
        # The encrypted JSON field round-trips an empty dict as None; either way, no env vars.
        self.assertFalse(env.environment_variables)
        user_env.refresh_from_db()
        self.assertFalse(user_env.internal)
        self.assertEqual(user_env.environment_variables, {"EXFIL_TARGET": "https://attacker.example"})

    def test_upsert_internal_sandbox_env_dedupes_only_internal_duplicates(self):
        # Concurrent upserts can double-insert (no unique constraint on (team, name)). The
        # dedupe must keep the oldest INTERNAL row, reassert policy on it, and never treat a
        # same-named user-created row as a duplicate to delete.
        user_env = SandboxEnvironment.objects.create(team=self.team, name="SIGNALS_X", internal=False)
        first = SandboxEnvironment.objects.create(team=self.team, name="SIGNALS_X", internal=True)
        second = SandboxEnvironment.objects.create(team=self.team, name="SIGNALS_X", internal=True)
        # Pin an unambiguous creation order so keeper selection is deterministic.
        SandboxEnvironment.objects.filter(id=first.id).update(created_at=django_timezone.now() - timedelta(minutes=1))

        env_id = facade.upsert_internal_sandbox_env(self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.FULL)

        self.assertEqual(str(env_id), str(first.id))
        self.assertFalse(SandboxEnvironment.objects.filter(id=second.id).exists())
        self.assertTrue(SandboxEnvironment.objects.filter(id=user_env.id).exists())
        first.refresh_from_db()
        self.assertEqual(first.network_access_level, SandboxEnvironment.NetworkAccessLevel.FULL.value)

    def test_upsert_internal_sandbox_env_scrubs_execution_fields(self):
        # Reasserting policy must cover the whole execution surface: env vars / repositories
        # set on the internal row between calls (however they got there) are cleared, so they
        # can never ride into the next internally provisioned run.
        env_id = facade.upsert_internal_sandbox_env(self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.TRUSTED)
        env = SandboxEnvironment.objects.get(id=env_id)
        env.environment_variables = {"INJECTED": "value"}
        env.repositories = ["attacker/repo"]
        env.save(update_fields=["environment_variables", "repositories"])

        env_id_2 = facade.upsert_internal_sandbox_env(
            self.team.id, "SIGNALS_X", facade.SandboxNetworkAccessLevel.TRUSTED
        )

        self.assertEqual(env_id_2, env_id)
        env.refresh_from_db()
        # The encrypted JSON field round-trips an empty dict as None; either way, no env vars.
        self.assertFalse(env.environment_variables)
        self.assertEqual(env.repositories, [])

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

    @patch("products.tasks.backend.logic.services.title_generator.generate_task_title")
    def test_create_task_names_from_naming_source_keeping_description_bare(self, mock_title):
        # When a client pastes text (stored as an attachment), it sends the pasted content as
        # naming_source so the title reads well, while description stays the bare prompt the
        # agent — and the reload transcript dedup — expect.
        mock_title.side_effect = lambda text: f"title:{text}"
        dto = facade.create_task(
            team_id=self.team.id,
            user_id=self.user.id,
            validated_data={
                "description": "Attached files: pasted-text.txt",
                "naming_source": "Deploy blocks on a stale lockfile",
                "origin_product": Task.OriginProduct.USER_CREATED,
            },
        )
        task = Task.objects.get(id=dto.id)
        self.assertEqual(task.description, "Attached files: pasted-text.txt")
        self.assertEqual(task.title, "title:Deploy blocks on a stale lockfile")
        self.assertFalse(task.title_manually_set)
        mock_title.assert_called_once_with("Deploy blocks on a stale lockfile")

    @patch("products.tasks.backend.logic.services.title_generator.generate_task_title")
    def test_create_task_falls_back_to_description_without_naming_source(self, mock_title):
        mock_title.side_effect = lambda text: f"title:{text}"
        dto = facade.create_task(
            team_id=self.team.id,
            user_id=self.user.id,
            validated_data={
                "description": "Fix the login redirect",
                "origin_product": Task.OriginProduct.USER_CREATED,
            },
        )
        task = Task.objects.get(id=dto.id)
        self.assertEqual(task.title, "title:Fix the login redirect")
        mock_title.assert_called_once_with("Fix the login redirect")

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

    def _make_channel(self, **kwargs) -> Channel:
        # unscoped: no ambient team_scope in these tests, and the fail-closed manager
        # raises on a bare write just as it does on a bare read.
        defaults = {
            "team": self.team,
            "name": "engineering",
            "channel_type": Channel.ChannelType.PUBLIC,
            "created_by": self.user,
        }
        return Channel.objects.unscoped().create(**{**defaults, **kwargs})

    def _make_teammates_personal_channel(self) -> Channel:
        teammate = User.objects.create(email="teammate@test.com", distinct_id="teammate")
        return self._make_channel(
            name=Channel.PERSONAL_CHANNEL_NAME,
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=teammate,
        )

    @parameterized.expand(
        [
            ("public", lambda self: self._make_channel().id, True),
            ("unknown", lambda _self: uuid4(), False),
            # Someone else's "#me" is private: filing into it would leak the task into
            # their personal feed, so it must be dropped like an unknown id.
            ("other_users_personal", lambda self: self._make_teammates_personal_channel().id, False),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_task_files_into_channel(self, _name, make_channel_id, expect_filed, _mock_workflow):
        Integration.objects.create(team=self.team, kind="github", config={})
        channel_id = make_channel_id(self)

        created = facade.create_and_run_task(
            team=self.team,
            title="Created via facade",
            description="desc",
            origin_product=facade.TaskOriginProduct.USER_CREATED,
            user_id=self.user.id,
            repository="posthog/posthog",
            channel_id=channel_id,
        )
        task = Task.objects.select_related("channel").get(id=created.task_id)
        if expect_filed:
            self.assertEqual(task.channel_id, channel_id)
        else:
            assert task.channel is not None
            self.assertEqual(task.channel.channel_type, Channel.ChannelType.PERSONAL)
            self.assertEqual(task.channel.created_by_id, self.user.id)

    @parameterized.expand(
        [
            ("public", lambda self: self._make_channel().id, True),
            ("unknown", lambda _self: uuid4(), False),
            # Same rule as create_and_run_task above: someone else's "#me" is private,
            # so filing into it must be refused, not just team-filtered.
            ("other_users_personal", lambda self: self._make_teammates_personal_channel().id, False),
        ]
    )
    def test_create_channel_task_respects_channel_visibility(self, _name, make_channel_id, expect_filed):
        channel_id = make_channel_id(self)

        if expect_filed:
            task_id = facade.create_channel_task(
                self.team.id, self.user.id, channel_id, title="From canvas", description="desc"
            )
            self.assertEqual(Task.objects.get(id=task_id).channel_id, channel_id)
        else:
            with self.assertRaises(ValueError):
                facade.create_channel_task(
                    self.team.id, self.user.id, channel_id, title="From canvas", description="desc"
                )

    def test_ensure_personal_channel_id_idempotent_outside_request_scope(self):
        # No ambient team_scope here, like a Temporal activity — guards the for_team scoping.
        first = facade.ensure_personal_channel_id(self.team.id, self.user.id)
        second = facade.ensure_personal_channel_id(self.team.id, self.user.id)
        self.assertEqual(first, second)
        self.assertEqual(
            list(
                Channel.objects.unscoped()
                .filter(team=self.team, channel_type=Channel.ChannelType.PERSONAL, deleted=False)
                .values_list("id", flat=True)
            ),
            [first],
        )
        # Callers outside Desktop file tasks through here, so an unstamped system space
        # would escape from this path.
        self.assertEqual(
            Channel.objects.unscoped().get(id=first).system_role,
            Channel.SystemRole.PERSONAL,
        )

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

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_wizard_cloud_run_pins_its_model(self, _mock_workflow):
        Integration.objects.create(team=self.team, kind="github", config={})
        created = facade.create_wizard_cloud_run(
            team=self.team,
            user_id=self.user.id,
            repository="acme-co/web",
        )
        run = TaskRun.objects.get(task_id=created.task_id)
        # Wizard runs route to the unbilled `onboarding` gateway product, which allowlists only
        # these models. Dropping the pin puts the run back on the agent-server's premium default,
        # which that product rejects, so every wizard cloud run would 403 at the gateway. Changing
        # the pin means changing the allowlist in services/llm-gateway too.
        self.assertEqual(run.state.get("runtime_adapter"), "claude")
        self.assertEqual(run.state.get("model"), "claude-sonnet-5")
        self.assertEqual(run.state.get("ai_stage"), "wizard_pr_agent")


class TestAppendLogAgentActivity(TestCase):
    # Guards the self-sustaining heartbeat loop: infra log lines (credential refresh ->
    # _posthog/console) heartbeating with agent_active=True reset the workflow's inactivity
    # timer on every write, so a run whose agent went silent could never time out.
    @parameterized.expand(
        [
            ("session_update", [{"notification": {"method": "session/update", "params": {}}}], True),
            ("session_request", [{"notification": {"method": "session/request_permission", "params": {}}}], True),
            ("console_only", [{"notification": {"method": "_posthog/console", "params": {"message": "x"}}}], False),
            ("error_only", [{"notification": {"method": "_posthog/error", "params": {}}}], False),
            # Non-ACP batches keep the old heartbeat behaviour: callers that only post generic
            # {type, message} entries have no session/* frame to offer and would otherwise lose
            # their inactivity extension while still working.
            ("no_notification", [{"message": "plain infra line"}], True),
            ("malformed_notification", [{"notification": "not-a-dict"}], True),
            ("non_string_method", [{"notification": {"method": 7}}], False),
            ("empty_entries", [], False),
            (
                "mixed_infra_and_session",
                [
                    {"notification": {"method": "_posthog/console", "params": {}}},
                    {"notification": {"method": "session/update", "params": {}}},
                ],
                True,
            ),
            # One ACP frame is enough to mark the batch as sandbox traffic, so the plain line
            # riding alongside it does not buy the credential-refresh batch a heartbeat.
            (
                "plain_line_alongside_infra_frame",
                [
                    {"message": "plain infra line"},
                    {"notification": {"method": "_posthog/console", "params": {}}},
                ],
                False,
            ),
        ]
    )
    def test_entries_show_agent_activity(self, _name, entries, expected):
        self.assertIs(facade._entries_show_agent_activity(entries), expected)

    def test_append_task_run_log_heartbeats_with_classified_activity(self):
        run = MagicMock()
        with (
            patch.object(facade, "_get_visible_run", return_value=run),
            patch.object(facade, "_task_run_detail_to_dto", return_value=None),
        ):
            facade.append_task_run_log(
                "r", "t", 1, entries=[{"notification": {"method": "_posthog/console", "params": {}}}]
            )
            run.heartbeat_workflow.assert_called_once_with(agent_active=False)
            run.reset_mock()
            facade.append_task_run_log("r", "t", 1, entries=[{"notification": {"method": "session/update"}}])
            run.heartbeat_workflow.assert_called_once_with(agent_active=True)


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


class TestSelfDrivingQuotaFacadeGates(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Quota Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Quota Team")
        cls.user = User.objects.create(email="quota-facade@test.com", distinct_id="quota-facade-distinct")

    def _enforced_gate(self):
        from products.signals.backend.quota import SelfDrivingQuotaGate

        return patch(
            "products.signals.backend.quota.self_driving_quota_gate",
            return_value=SelfDrivingQuotaGate(limited=True, enforced=True),
        )

    def test_create_and_run_task_blocked_for_self_driving_origin_when_enforced(self):
        # The implementation task is the step that leads to the billable PR; over-quota teams
        # must not get one through the facade regardless of caller.
        from posthog.exceptions import QuotaLimitExceeded

        with (
            self._enforced_gate(),
            patch("products.signals.backend.quota.capture_signal_report_quota_paused") as capture_mock,
            self.assertRaises(QuotaLimitExceeded),
        ):
            facade.create_and_run_task(
                team=self.team,
                title="Implementation: t",
                description="d",
                origin_product=facade.TaskOriginProduct.SIGNAL_REPORT,
                user_id=self.user.id,
                repository="posthog/posthog",
            )
        self.assertFalse(Task.objects.filter(team=self.team).exists())
        # The facade gate keeps its own stage: its main caller is the auto-start pipeline, whose
        # over-quota hits must not pollute the manual-path (`manual_create`) telemetry bucket.
        self.assertEqual(capture_mock.call_args.kwargs["stage"], "task_create")
        self.assertTrue(capture_mock.call_args.kwargs["enforced"])

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_task_allows_non_pr_sessions_when_enforced(self, _mock_workflow):
        # Research / repo-selection sessions create SIGNAL_REPORT tasks with create_pr=False;
        # they can never open the billable PR, and blocking them would hard-fail the pipeline
        # mid-run instead of letting the summary gates pause it.
        Integration.objects.create(team=self.team, kind="github", config={})
        with self._enforced_gate():
            created = facade.create_and_run_task(
                team=self.team,
                title="Research: t",
                description="d",
                origin_product=facade.TaskOriginProduct.SIGNAL_REPORT,
                user_id=self.user.id,
                repository="posthog/posthog",
                create_pr=False,
            )
        self.assertTrue(Task.objects.filter(id=created.task_id).exists())

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_task_dark_launch_emits_without_blocking(self, _mock_workflow):
        # Limited without enforcement must create the task and still emit the would-block
        # event, or the manual gate is invisible during the dark launch.
        from products.signals.backend.quota import SelfDrivingQuotaGate

        Integration.objects.create(team=self.team, kind="github", config={})
        with (
            patch(
                "products.signals.backend.quota.self_driving_quota_gate",
                return_value=SelfDrivingQuotaGate(limited=True, enforced=False),
            ),
            patch("products.signals.backend.quota.capture_signal_report_quota_paused") as capture_mock,
        ):
            created = facade.create_and_run_task(
                team=self.team,
                title="Implementation: t",
                description="d",
                origin_product=facade.TaskOriginProduct.SIGNAL_REPORT,
                user_id=self.user.id,
                repository="posthog/posthog",
            )
        self.assertTrue(Task.objects.filter(id=created.task_id).exists())
        self.assertEqual(capture_mock.call_args.kwargs["stage"], "task_create")
        self.assertFalse(capture_mock.call_args.kwargs["enforced"])

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_and_run_task_unaffected_for_other_origins_when_enforced(self, _mock_workflow):
        # The self-driving PR limit must never block user-created tasks.
        Integration.objects.create(team=self.team, kind="github", config={})
        with self._enforced_gate():
            created = facade.create_and_run_task(
                team=self.team,
                title="User task",
                description="d",
                origin_product=facade.TaskOriginProduct.USER_CREATED,
                user_id=self.user.id,
                repository="posthog/posthog",
            )
        self.assertTrue(Task.objects.filter(id=created.task_id).exists())

    @parameterized.expand([(None,), ("implementation",), ("discussion",)])
    def test_create_task_blocked_for_manual_report_creation_when_enforced(self, relationship):
        # The inbox "start work from report" path (write serializer binds `signal_report`).
        # Every relationship label is gated: the label is client-selected and manual tasks run
        # PR-capable by default, so a "discussion" label must not dodge the limit.
        from django.apps import apps

        from posthog.exceptions import QuotaLimitExceeded

        SignalReport = apps.get_model("signals", "SignalReport")
        report = SignalReport.objects.create(team=self.team, status="ready", title="t", summary="s")
        with (
            self._enforced_gate(),
            patch("products.signals.backend.quota.capture_signal_report_quota_paused") as capture_mock,
            self.assertRaises(QuotaLimitExceeded),
        ):
            facade.create_task(
                self.team.id,
                self.user.id,
                validated_data={
                    "title": "Implementation: t",
                    "description": "d",
                    "origin_product": Task.OriginProduct.SIGNAL_REPORT,
                    "signal_report": report,
                    "signal_report_task_relationship": relationship,
                },
            )
        self.assertFalse(Task.objects.filter(team=self.team).exists())
        # Genuinely manual creations keep the `manual_create` stage, distinct from the facade
        # backstop's `task_create`.
        self.assertEqual(capture_mock.call_args.kwargs["stage"], "manual_create")


class TestSelfDrivingQuotaRefreshDispatch(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Refresh Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Refresh Team")
        cls.user = User.objects.create(email="refresh@test.com", distinct_id="refresh-distinct")

    def _self_driving_run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="Implementation: t",
            description="d",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            created_by=self.user,
        )
        return TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

    @parameterized.expand(
        [
            # First PR URL on a self-driving-origin run is the billable moment: re-evaluate now.
            ("first_pr_dispatches", None, {"pr_url": "https://github.com/x/y/pull/1"}, True),
            # A repeat write for the same PR must not spam the quota task.
            (
                "repeat_write_skipped",
                "https://github.com/x/y/pull/1",
                {"pr_url": "https://github.com/x/y/pull/1"},
                False,
            ),
            # No PR in the output: nothing billable happened.
            ("no_pr_skipped", None, {"summary": "wip"}, False),
            # Billing only counts GitHub PR URLs; anything else must not enqueue a refresh.
            ("non_github_pr_url_skipped", None, {"pr_url": "https://evil.example/pr/1"}, False),
        ]
    )
    @patch("ee.tasks.quota_limiting.refresh_org_self_driving_quota_task")
    def test_refresh_dispatch_on_first_pr(self, _name, old_pr_url, output, expect_dispatch, task_mock):
        run = self._self_driving_run()
        run.output = output
        run.save(update_fields=["output"])
        with self.captureOnCommitCallbacks(execute=True):
            facade._refresh_self_driving_quota_for_pr(run, old_pr_url)
        self.assertEqual(task_mock.delay.call_count, 1 if expect_dispatch else 0)
        if expect_dispatch:
            self.assertEqual(task_mock.delay.call_args.args, (str(self.organization.id),))

    @patch("ee.tasks.quota_limiting.refresh_org_self_driving_quota_task")
    def test_refresh_swallows_lookup_failure(self, task_mock):
        # The refresh is best-effort (the quota cron is the backstop): a transient DB fault must
        # not propagate, or it would 500 an already-committed run write and abort the completion
        # signaling that follows at both call sites.
        run = self._self_driving_run()
        run.output = {"pr_url": "https://github.com/x/y/pull/1"}
        run.save(update_fields=["output"])
        with patch("products.tasks.backend.facade.api.Team.objects.filter", side_effect=RuntimeError("db down")):
            facade._refresh_self_driving_quota_for_pr(run, None)
        task_mock.delay.assert_not_called()

    @patch("ee.tasks.quota_limiting.refresh_org_self_driving_quota_task")
    def test_refresh_dispatch_skipped_for_other_origins(self, task_mock):
        run = self._self_driving_run()
        run.task.origin_product = Task.OriginProduct.USER_CREATED
        run.task.save(update_fields=["origin_product"])
        run.output = {"pr_url": "https://github.com/x/y/pull/1"}
        run.save(update_fields=["output"])
        with self.captureOnCommitCallbacks(execute=True):
            facade._refresh_self_driving_quota_for_pr(run, None)
        task_mock.delay.assert_not_called()


class TestApplyTaskRunModelConfig(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Config Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Config Team")
        cls.user = User.objects.create(email="config@test.com", distinct_id="config-distinct")

    def _run(self) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="A task",
            description="desc",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            repository="posthog/posthog",
        )
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"runtime_adapter": "claude", "model": "claude-sonnet-4-6", "sandbox_url": "https://sandbox"},
        )

    def _apply(self, run: TaskRun, **kwargs) -> bool:
        return facade.apply_task_run_model_config(run.id, run.task_id, self.team.id, **kwargs)

    @patch("products.tasks.backend.logic.services.agent_command.send_set_config_option")
    def test_sends_the_model_before_the_effort_and_records_both(self, send_mock):
        # Which efforts exist depends on the model, so the agent-server has to see the
        # model change first or it validates the effort against the outgoing one.
        send_mock.return_value = MagicMock(success=True)
        run = self._run()

        applied = self._apply(run, model="claude-fable-5", reasoning_effort="xhigh")

        self.assertTrue(applied)
        self.assertEqual(
            [(c.args[1], c.args[2]) for c in send_mock.call_args_list],
            [("model", "claude-fable-5"), ("effort", "xhigh")],
        )
        run.refresh_from_db()
        self.assertEqual(run.state["model"], "claude-fable-5")
        self.assertEqual(run.state["reasoning_effort"], "xhigh")

    @patch("products.tasks.backend.logic.services.agent_command.send_set_config_option")
    def test_a_rejected_model_leaves_the_effort_alone(self, send_mock):
        # The agent-server rejects a model its harness can't drive. Sending the effort
        # anyway would half-apply a single request onto the model the author didn't ask for.
        send_mock.return_value = MagicMock(success=False, error="Invalid value for config option model")
        run = self._run()

        applied = self._apply(run, model="gpt-5.6-sol", reasoning_effort="xhigh")

        self.assertFalse(applied)
        self.assertEqual(send_mock.call_count, 1)
        run.refresh_from_db()
        self.assertEqual(run.state["model"], "claude-sonnet-4-6")
        self.assertNotIn("reasoning_effort", run.state)

    @patch("products.tasks.backend.facade.api.get_model_access_error", return_value="'x' is not available.")
    @patch("products.tasks.backend.logic.services.agent_command.send_set_config_option")
    def test_a_gated_model_never_reaches_the_sandbox(self, send_mock, _access_mock):
        run = self._run()

        self.assertFalse(self._apply(run, model="claude-fable-5", actor_user_id=self.user.id))
        send_mock.assert_not_called()

    @patch("products.tasks.backend.logic.services.agent_command.send_set_config_option")
    def test_nothing_to_change_is_not_a_sandbox_call(self, send_mock):
        self.assertFalse(self._apply(self._run()))
        send_mock.assert_not_called()


class TestDesktopUsersInTeam(TestCase):
    def test_someone_who_left_the_organization_is_not_welcomed(self) -> None:
        organization = Organization.objects.create(name="Members Org")
        team = Team.objects.create(organization=organization, name="Project")
        arriving = User.objects.create(email="arriving@test.com", distinct_id="arriving")
        staying = User.objects.create(email="staying@test.com", distinct_id="staying")
        leaving = User.objects.create(email="leaving@test.com", distinct_id="leaving")
        for user in (arriving, staying, leaving):
            OrganizationMembership.objects.create(organization=organization, user=user)
            with team_scope(team.id):
                facade.provision_default_channels(team.id, user.id)

        OrganizationMembership.objects.filter(organization=organization, user=leaving).delete()

        with team_scope(team.id):
            names = facade.desktop_users_in_team(team, arriving.id)

        assert names == ["staying"]

    def test_a_space_from_before_system_role_still_counts_as_a_member(self) -> None:
        organization = Organization.objects.create(name="Legacy Org")
        team = Team.objects.create(organization=organization, name="Project")
        arriving = User.objects.create(email="arriving2@test.com", distinct_id="arriving2")
        settled = User.objects.create(email="settled@test.com", distinct_id="settled")
        for user in (arriving, settled):
            OrganizationMembership.objects.create(organization=organization, user=user)
            with team_scope(team.id):
                facade.provision_default_channels(team.id, user.id)
        # system_role is stamped lazily, so a space nobody has opened Desktop on since the field
        # landed still carries NULL.
        with team_scope(team.id):
            Channel.objects.filter(team_id=team.id, created_by=settled).update(system_role=None)

        with team_scope(team.id):
            names = facade.desktop_users_in_team(team, arriving.id)

        assert names == ["settled"]

    def test_someone_without_private_project_access_is_not_welcomed(self) -> None:
        organization = Organization.objects.create(name="Private Project Org")
        team = Team.objects.create(organization=organization, name="Private Project")
        arriving = User.objects.create(email="arriving-private@test.com", distinct_id="arriving-private")
        revoked = User.objects.create(email="revoked@test.com", distinct_id="revoked")
        for user in (arriving, revoked):
            OrganizationMembership.objects.create(organization=organization, user=user)
            with team_scope(team.id):
                facade.provision_default_channels(team.id, user.id)

        organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        organization.save(update_fields=["available_product_features"])
        OrganizationMembership.objects.filter(organization=organization, user=arriving).update(
            level=OrganizationMembership.Level.ADMIN
        )
        AccessControl.objects.create(
            team=team,
            resource="project",
            resource_id=str(team.id),
            access_level="none",
        )

        with team_scope(team.id):
            names = facade.desktop_users_in_team(team, arriving.id)

        assert names == []


class TestOrganizationHasContext(TestCase):
    organization: ClassVar[Organization]
    user: ClassVar[User]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Context Org")
        cls.user = User.objects.create(email="context@test.com", distinct_id="context-distinct")

    def _team(self, name: str) -> Team:
        return Team.objects.create(organization=self.organization, name=name)

    def _provision_general(self, team: Team) -> UUID:
        with team_scope(team.id):
            facade.provision_default_channels(team.id, self.user.id)
            channel_id = facade.find_general_channel_id(team.id)
        assert channel_id is not None
        return channel_id

    def _publish_general(self, team: Team, content: str) -> None:
        channel_id = self._provision_general(team)
        with team_scope(team.id):
            facade.publish_channel_instructions(channel_id, team.id, self.user.id, content=content)

    def test_a_general_space_from_before_system_role_still_carries_context(self) -> None:
        team = self._team("Legacy project")
        self._publish_general(team, "We make climbing gear.")
        # Same lazy stamping as personal spaces: an org-wide read that only matched the stamped
        # shape would rescrape and re-ask a company that has already answered.
        with team_scope(team.id):
            Channel.objects.filter(team_id=team.id).update(system_role=None)

        self.assertTrue(facade.organization_has_context(self.organization.id))

    @parameterized.expand([("no_general_space", False), ("blank_general_space", True)])
    def test_context_in_one_team_answers_for_the_whole_org(self, _name: str, provision_sibling: bool) -> None:
        # The context-less project is created first so the scan reaches it before the one
        # holding the context: a per-project answer would stop there and report "no".
        sibling = self._team("Project A")
        if provision_sibling:
            self._provision_general(sibling)
        self._publish_general(self._team("Project B"), "We make climbing gear.")

        self.assertTrue(facade.organization_has_context(self.organization.id))

    @parameterized.expand(
        [
            ("no_general_space", "none"),
            ("general_space_never_published", "provisioned"),
            ("published_instructions_are_blank", "blank"),
        ]
    )
    def test_returns_false_without_usable_instructions(self, _name: str, setup: str) -> None:
        team = self._team("Project A")
        if setup == "provisioned":
            self._provision_general(team)
        elif setup == "blank":
            self._publish_general(team, "   \n")

        self.assertFalse(facade.organization_has_context(self.organization.id))

    def test_another_organizations_context_does_not_count(self) -> None:
        self._provision_general(self._team("Project A"))
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Project")
        with team_scope(other_team.id):
            facade.provision_default_channels(other_team.id, self.user.id)
            other_channel = facade.find_general_channel_id(other_team.id)
            assert other_channel is not None
            facade.publish_channel_instructions(other_channel, other_team.id, self.user.id, content="They make bikes.")

        self.assertFalse(facade.organization_has_context(self.organization.id))
        self.assertTrue(facade.organization_has_context(other_org.id))
