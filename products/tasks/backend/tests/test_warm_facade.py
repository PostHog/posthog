from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone as django_timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, Throttled

from posthog.exceptions import QuotaLimitExceeded
from posthog.models import Integration, User

from products.tasks.backend.facade import (
    access as tasks_access,
    api as facade,
    contracts,
)
from products.tasks.backend.logic.services.staged_artifacts import (
    build_task_artifact_entry,
    build_task_staged_artifact_cache_key,
)
from products.tasks.backend.logic.services.warm import WarmResult
from products.tasks.backend.models import (
    TASK_OWNERSHIP_VERSION_STATE_KEY,
    SandboxCustomImage,
    SandboxEnvironment,
    Task,
    TaskRun,
)
from products.tasks.backend.redis import get_tasks_cache

FACADE = "products.tasks.backend.facade.api"


def _artifact_entry(artifact_id: str) -> dict[str, Any]:
    return build_task_artifact_entry(
        artifact_id=artifact_id,
        name="millie.zip",
        artifact_type="skill_bundle",
        source="user_attachment",
        size=128,
        content_type="application/zip",
        storage_path=f"tasks/artifacts/{artifact_id}/millie.zip",
        metadata={
            "skill_name": "millie",
            "skill_source": "user",
            "content_sha256": "a" * 64,
            "bundle_format": "zip",
            "schema_version": 1,
        },
    )


WARM_SRC = "products.tasks.backend.logic.services.warm.SandboxWarmer"
TITLE_SRC = "products.tasks.backend.logic.services.title_generator"


def _allow_desktop_access(test_case: APIBaseTest) -> None:
    access_patcher = patch(
        "products.tasks.backend.logic.services.code_usage_gate.get_desktop_access_decision",
        return_value=tasks_access.DesktopAccessDecision.ALLOWED,
    )
    access_patcher.start()
    test_case.addCleanup(access_patcher.stop)


class TestWarmTaskSandbox(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})
        # The warm endpoint gates on Desktop access; these tests cover warm forwarding, not the gate.
        _allow_desktop_access(self)

    def _warm(self, **overrides):
        kwargs: dict[str, Any] = {
            "team_id": self.team.id,
            "user_id": self.user.id,
            "repository": "posthog/posthog",
            "github_integration_id": self.integration.id,
            "branch": "main",
        }
        kwargs.update(overrides)
        return facade.warm_task_sandbox(**kwargs)

    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    @patch("products.tasks.backend.facade.api.warm_task_sandbox")
    def test_warm_endpoint_forwards_sandbox_selection(self, mock_warm, _mock_warm_enabled):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        custom_image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name="Custom image",
            status=SandboxCustomImage.Status.READY,
            modal_image_name="custom-image:v1",
        )
        mock_warm.return_value = None

        response = self.client.post(
            "/api/projects/@current/tasks/warm/",
            {
                "repository": "posthog/posthog",
                "github_integration": self.integration.id,
                "branch": "main",
                "sandbox_environment_id": str(sandbox_environment.id),
                "custom_image_id": str(custom_image.id),
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert mock_warm.call_args.kwargs["sandbox_environment_id"] == sandbox_environment.id
        assert mock_warm.call_args.kwargs["custom_image_id"] == custom_image.id

    @parameterized.expand(
        [
            ("posthog_ai_warms_with_every_flag_off", facade.TaskOriginProduct.POSTHOG_AI, False, True),
            ("code_app_stays_gated_when_off", facade.TaskOriginProduct.USER_CREATED, False, False),
            ("code_app_warms_when_on", facade.TaskOriginProduct.USER_CREATED, True, True),
        ]
    )
    def test_origin_product_decides_whether_a_flag_gates_warming(
        self, _name: str, origin_product: str, flag_enabled: bool, should_warm: bool
    ):
        with (
            patch("products.tasks.backend.facade.api.warm_task_sandbox") as mock_warm,
            patch(
                "products.tasks.backend.presentation.views.api.posthoganalytics.feature_enabled",
                return_value=flag_enabled,
            ),
        ):
            mock_warm.return_value = None
            response = self.client.post(
                "/api/projects/@current/tasks/warm/",
                {
                    "repository": "posthog/posthog",
                    "github_integration": self.integration.id,
                    "branch": "main",
                    "origin_product": origin_product,
                },
                format="json",
            )

        assert response.status_code == 200, response.content
        assert mock_warm.called is should_warm

    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    @patch("products.tasks.backend.facade.api.warm_task_resume_sandbox")
    def test_resume_warm_endpoint_forwards_terminal_run_selection(self, mock_warm, _mock_warm_enabled):
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        terminal = task.create_run(mode="interactive")
        terminal.status = TaskRun.Status.CANCELLED
        terminal.save(update_fields=["status"])
        mock_warm.return_value = contracts.WarmTaskDTO(task_id=task.id, run_id=terminal.id)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/warm/",
            {
                "resume_from_run_id": str(terminal.id),
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "reasoning_effort": "high",
                "initial_permission_mode": "plan",
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        mock_warm.assert_called_once_with(
            str(task.id),
            self.team.id,
            self.user.id,
            resume_from_run_id=terminal.id,
            runtime_adapter="claude",
            model="claude-sonnet-5",
            reasoning_effort="high",
            initial_permission_mode="plan",
        )

    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    @patch("products.tasks.backend.facade.api.warm_task_sandbox")
    def test_warm_endpoint_accepts_repo_less_request(self, mock_warm, _mock_warm_enabled):
        mock_warm.return_value = None

        response = self.client.post(
            "/api/projects/@current/tasks/warm/",
            {"repository": None, "github_integration": None, "branch": None},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert mock_warm.call_args.kwargs["repository"] is None
        assert mock_warm.call_args.kwargs["github_integration_id"] is None

    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    def test_warm_endpoint_rejects_duplicate_repositories(self, _mock_warm_enabled):
        response = self.client.post(
            "/api/projects/@current/tasks/warm/",
            {
                "repositories": ["PostHog/PostHog", "posthog/posthog"],
                "github_integration": self.integration.id,
            },
            format="json",
        )

        assert response.status_code == 400
        assert b"Repositories must be unique" in response.content

    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    def test_warm_endpoint_limits_repository_clone_budget(self, _mock_warm_enabled):
        response = self.client.post(
            "/api/projects/@current/tasks/warm/",
            {
                "repositories": ["posthog/one", "posthog/two", "posthog/three", "posthog/four"],
                "github_integration": self.integration.id,
            },
            format="json",
        )

        assert response.status_code == 400

    @parameterized.expand(
        [
            (
                "claude_rejects_codex_mode",
                "claude",
                "claude-opus-4-6",
                "full-access",
            ),
            (
                "codex_rejects_claude_mode",
                "codex",
                "gpt-5.4",
                "bypassPermissions",
            ),
            ("mode_without_a_runtime", None, None, "plan"),
        ]
    )
    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    @patch("products.tasks.backend.facade.api.warm_task_sandbox")
    def test_warm_endpoint_rejects_mismatched_permission_mode(
        self,
        _case_name,
        runtime_adapter,
        model,
        initial_permission_mode,
        mock_warm,
        _mock_warm_enabled,
    ):
        # The mode is fixed when the sandbox boots, so a pair the run request would reject must not
        # reach one here either — the submit that follows would be rejected against a booted sandbox.
        response = self.client.post(
            "/api/projects/@current/tasks/warm/",
            {
                "repository": "posthog/posthog",
                "github_integration": self.integration.id,
                "branch": "main",
                "runtime_adapter": runtime_adapter,
                "model": model,
                "initial_permission_mode": initial_permission_mode,
            },
            format="json",
        )

        assert response.status_code == 400, response.content
        assert response.json()["attr"] == "initial_permission_mode"
        mock_warm.assert_not_called()

    def test_provisions_selected_sandbox_environment_and_custom_image(self):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        custom_image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name="Custom image",
            status=SandboxCustomImage.Status.READY,
            modal_image_name="custom-image:v1",
        )

        def fake_warm(self_warmer, **kwargs):
            run = self_warmer.task.create_run(mode="interactive", extra_state=kwargs["extra_state"])
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm):
            result = self._warm(
                sandbox_environment_id=sandbox_environment.id,
                custom_image_id=custom_image.id,
            )

        assert result is not None
        run = TaskRun.objects.get(id=result.run_id)
        assert run.state["sandbox_environment_id"] == str(sandbox_environment.id)
        assert run.state["custom_image_id"] == str(custom_image.id)
        assert "use_modal_network_allowlist" not in run.state

    def test_births_draft_task_and_returns_warm_dto(self):
        def fake_warm(self_warmer, **kwargs):
            run = self_warmer.task.create_run(mode="interactive", extra_state={"await_user_message": True})
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm):
            result = self._warm()

        assert isinstance(result, contracts.WarmTaskDTO)
        task = Task.objects.get(id=result.task_id)
        assert task.origin_product == Task.OriginProduct.USER_CREATED
        assert task.created_by_id == self.user.id
        assert task.repository == "posthog/posthog"
        assert task.github_integration_id == self.integration.id
        assert task.description == ""
        assert task.runs.filter(id=result.run_id).exists()

    def test_births_repo_less_draft_and_returns_warm_dto(self):
        def fake_warm(self_warmer, **kwargs):
            run = self_warmer.task.create_run(mode="interactive", extra_state={"await_user_message": True})
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm):
            result = self._warm(repository=None, github_integration_id=None, branch=None)

        assert result is not None
        task = Task.objects.get(id=result.task_id)
        assert task.repository is None

    def test_births_multi_repository_draft(self):
        def fake_warm(self_warmer, **kwargs):
            run = self_warmer.task.create_run(mode="interactive", extra_state={"await_user_message": True})
            return WarmResult(run=run, just_created=True)

        repositories = ["posthog/posthog", "posthog/posthog-js"]
        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm):
            result = self._warm(repositories=repositories)

        assert result is not None
        task = Task.objects.get(id=result.task_id)
        run = TaskRun.objects.get(id=result.run_id)
        assert task.repository == repositories[0]
        assert task.repositories == repositories
        assert run.state["repositories"] == repositories

    def test_returns_none_and_soft_deletes_draft_when_capped(self):
        with patch(f"{WARM_SRC}.warm", side_effect=Throttled()):
            result = self._warm()

        assert result is None
        task = Task.objects.get(team=self.team)
        assert task.deleted is True

    def test_returns_none_when_quota_exceeded(self):
        with patch(f"{WARM_SRC}.warm", side_effect=QuotaLimitExceeded("over")):
            result = self._warm()
        assert result is None
        assert Task.objects.get(team=self.team).deleted is True

    def test_returns_none_when_product_not_enabled(self):
        with patch(f"{WARM_SRC}.warm", side_effect=PermissionDenied()):
            result = self._warm()
        assert result is None
        assert Task.objects.get(team=self.team).deleted is True

    def test_returns_none_when_github_integration_missing(self):
        with patch(f"{WARM_SRC}.warm") as m_warm:
            result = self._warm(github_integration_id=self.integration.id + 9999)
        assert result is None
        m_warm.assert_not_called()
        assert not Task.objects.filter(team=self.team).exists()

    def test_dedups_an_existing_idling_warm_for_the_same_selection(self):
        def fake_warm(self_warmer, **kwargs):
            run = self_warmer.task.create_run(
                mode="interactive", extra_state={"await_user_message": True, "branch": "main"}, branch="main"
            )
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm) as m_warm:
            first = self._warm()
            second = self._warm()

        assert first is not None and second is not None
        assert second.run_id == first.run_id
        assert second.task_id == first.task_id
        m_warm.assert_called_once()
        assert Task.objects.filter(team=self.team, deleted=False).count() == 1

    def test_dedups_when_only_reasoning_effort_changes(self):
        def fake_warm(self_warmer, **kwargs):
            state = {"await_user_message": True, **kwargs["extra_state"]}
            run = self_warmer.task.create_run(mode="interactive", extra_state=state, branch=state.get("branch"))
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm) as mock_warm:
            first = self._warm(runtime_adapter="codex", model="gpt-5.6-sol", reasoning_effort="high")
            second = self._warm(runtime_adapter="codex", model="gpt-5.6-sol", reasoning_effort="xhigh")

        assert first is not None and second is not None
        assert second.run_id == first.run_id
        mock_warm.assert_called_once()

    def test_does_not_reuse_warm_run_after_environment_access_is_revoked(self):
        other_user = User.objects.create_and_join(self.organization, "other-warm-owner@posthog.com", None)
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=other_user,
            name="Shared environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
            private=False,
        )

        def fake_warm(self_warmer, **kwargs):
            state = kwargs["extra_state"]
            run = self_warmer.task.create_run(mode="interactive", extra_state=state, branch=state.get("branch"))
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm) as mock_warm:
            first = self._warm(sandbox_environment_id=sandbox_environment.id)
            sandbox_environment.private = True
            sandbox_environment.save(update_fields=["private", "updated_at"])
            second = self._warm(sandbox_environment_id=sandbox_environment.id)

        assert first is not None
        assert second is None
        mock_warm.assert_called_once()

    def test_does_not_dedup_across_different_sandbox_environments(self):
        first_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="First environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        second_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Second environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )

        def fake_warm(self_warmer, **kwargs):
            state = kwargs["extra_state"]
            run = self_warmer.task.create_run(mode="interactive", extra_state=state, branch=state.get("branch"))
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm) as mock_warm:
            first = self._warm(sandbox_environment_id=first_environment.id)
            second = self._warm(sandbox_environment_id=second_environment.id)

        assert first is not None and second is not None
        assert second.run_id != first.run_id
        assert mock_warm.call_count == 2

    def test_does_not_dedup_across_a_different_branch(self):
        def fake_warm(self_warmer, **kwargs):
            branch = (kwargs.get("extra_state") or {}).get("branch")
            run = self_warmer.task.create_run(
                mode="interactive", extra_state={"await_user_message": True, "branch": branch}, branch=branch
            )
            return WarmResult(run=run, just_created=True)

        with patch(f"{WARM_SRC}.warm", autospec=True, side_effect=fake_warm) as m_warm:
            first = self._warm(branch="main")
            second = self._warm(branch="feature/x")

        assert first is not None and second is not None
        assert second.run_id != first.run_id
        assert m_warm.call_count == 2


class TestCreateTaskWarmReuse(APIBaseTest):
    """The normal create path reuses a matching idling warm Run instead of minting a cold Task."""

    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={},
            repository_cache=[{"id": 1, "name": "posthog", "full_name": "posthog/posthog"}],
            repository_cache_updated_at=django_timezone.now(),
        )
        _allow_desktop_access(self)

    def _warm_run(
        self,
        *,
        repository="posthog/posthog",
        repositories: list[str] | None = None,
        branch="main",
        created_by=None,
        extra_state: dict[str, Any] | None = None,
        origin_product=Task.OriginProduct.USER_CREATED,
    ) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=origin_product,
            created_by=created_by or self.user,
            repository=repository,
            repositories=repositories or ([repository] if repository else []),
            github_integration=self.integration if repository else None,
        )
        run = task.create_run(
            mode="interactive",
            extra_state={"await_user_message": True, "branch": branch, **(extra_state or {})},
            branch=branch,
        )
        return task, run

    def _create(self, **data):
        validated = {
            "description": "fix the bug",
            "repository": "posthog/posthog",
            "github_integration": self.integration,
            "branch": "main",
        }
        validated.update(data)
        return facade.create_task(self.team.id, self.user.id, validated_data=validated)

    def test_desktop_create_without_permission_mode_still_reuses_warm(self):
        # A warm Run's state always carries a concrete permission mode, but the Code app never sends one
        # on create. Folding the mode into the equality tuple would compare None against "default" and
        # break every Desktop warm reuse — this pins the asymmetric comparison that prevents it.
        warm_task, run = self._warm_run(extra_state={"initial_permission_mode": "default"})
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create()

        assert str(dto.id) == str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 1

    def test_reuses_matching_posthog_ai_warm_task(self):
        warm_task, run = self._warm_run(
            origin_product=Task.OriginProduct.POSTHOG_AI,
            extra_state={"initial_permission_mode": "auto"},
        )
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create(origin_product=Task.OriginProduct.POSTHOG_AI, initial_permission_mode="auto")

        assert str(dto.id) == str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 1

    @parameterized.expand(
        [
            ("warm_is_code_submit_is_phai", Task.OriginProduct.USER_CREATED, Task.OriginProduct.POSTHOG_AI),
            ("warm_is_phai_submit_is_code", Task.OriginProduct.POSTHOG_AI, Task.OriginProduct.USER_CREATED),
        ]
    )
    def test_does_not_reuse_a_warm_from_a_different_origin_product(self, _name, warm_origin, submit_origin):
        # Origin fixes the OAuth app, the quota gate, the pool budget and PR authorship at boot, so a
        # cross-origin reuse would run under the wrong product's entitlements and authorship.
        self._warm_run(origin_product=warm_origin)
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create(origin_product=submit_origin)

        assert Task.objects.filter(team=self.team, deleted=False).count() == 2
        assert str(dto.origin_product) == submit_origin

    def test_permission_mode_mismatch_creates_a_new_cold_task(self):
        # The mode is read when the agent session is constructed, so a warm booted on one mode can't
        # serve a submit that asked for another.
        self._warm_run(extra_state={"initial_permission_mode": "default"})
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            self._create(initial_permission_mode="bypassPermissions")

        assert Task.objects.filter(team=self.team, deleted=False).count() == 2

    def test_reuses_matching_warm_task_and_activates_it_in_place(self):
        warm_task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            dto = self._create(auto_publish=True)

        assert str(dto.id) == str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 1
        warm_task.refresh_from_db()
        run.refresh_from_db()
        assert warm_task.description == "fix the bug"
        assert warm_task.title
        m_signal.assert_called_once()
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == "fix the bug"
        assert "await_user_message" not in run.state
        # The agent-server re-reads run state on the forwarded first message, so this
        # must be persisted for the warm run to honor the setting.
        assert run.state.get("auto_publish") is True

    def test_reuses_warm_task_with_new_reasoning_effort_and_attachments(self):
        warm_task, run = self._warm_run(
            extra_state={
                "runtime_adapter": "codex",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
            }
        )
        run.artifacts = [_artifact_entry("artifact-1")]
        run.save(update_fields=["artifacts"])

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as mock_signal:
            dto = self._create(
                runtime_adapter="codex",
                model="gpt-5.6-sol",
                reasoning_effort="xhigh",
                pending_user_message="inspect the attachment",
                pending_user_artifact_ids=["artifact-1"],
            )

        assert str(dto.id) == str(warm_task.id)
        run.refresh_from_db()
        assert run.state.get("reasoning_effort") == "xhigh"
        assert "await_user_message" not in run.state
        _, kwargs = mock_signal.call_args
        assert kwargs["artifact_ids"] == ["artifact-1"]

    def test_reuses_warm_task_without_reasoning_effort_and_clears_prewarm_value(self):
        warm_task, run = self._warm_run(
            extra_state={
                "runtime_adapter": "codex",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
            }
        )

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create(runtime_adapter="codex", model="gpt-5.6-sol")

        assert str(dto.id) == str(warm_task.id)
        run.refresh_from_db()
        assert "reasoning_effort" not in run.state
        assert "await_user_message" not in run.state

    def test_reuses_matching_multi_repository_warm_task(self):
        repositories = ["posthog/posthog", "posthog/posthog-js"]
        warm_task, run = self._warm_run(repositories=repositories)

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create(repositories=repositories, github_integration=self.integration)

        assert str(dto.id) == str(warm_task.id)
        run.refresh_from_db()
        assert "await_user_message" not in run.state

    def test_does_not_reuse_warm_task_from_a_different_github_integration(self):
        warm_task, _ = self._warm_run()
        other_integration = Integration.objects.create(team=self.team, kind="github", config={})

        dto = self._create(github_integration=other_integration)

        assert str(dto.id) != str(warm_task.id)

    def test_reuses_matching_repo_less_warm_task(self):
        warm_task, run = self._warm_run(repository=None, branch=None)
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            dto = self._create(repository=None, github_integration=None, branch=None)

        assert str(dto.id) == str(warm_task.id)
        run.refresh_from_db()
        assert "await_user_message" not in run.state

    def test_create_endpoint_returns_structured_compute_quota_denial_before_warm_activation(self):
        warm_task, run = self._warm_run()

        with patch(
            "products.tasks.backend.logic.services.compute_quota.get_compute_quota_denial_reason",
            return_value="posthog_code_billing_limit_exceeded",
        ):
            response = self.client.post(
                "/api/projects/@current/tasks/",
                {"description": "fix the bug", "repository": "posthog/posthog", "branch": "main"},
                format="json",
            )

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["code"] == "posthog_code_billing_limit_exceeded"
        warm_task.refresh_from_db()
        run.refresh_from_db()
        assert warm_task.description == ""
        assert run.state.get("await_user_message") is True

    def test_does_not_overwrite_existing_warm_description(self):
        warm_task, _ = self._warm_run()
        warm_task.description = "already there"
        warm_task.save(update_fields=["description"])

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            self._create(description="new prompt")
        warm_task.refresh_from_db()
        assert warm_task.description == "already there"

    def test_branch_mismatch_creates_a_new_cold_task(self):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        custom_image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name="Custom image",
            status=SandboxCustomImage.Status.READY,
            modal_image_name="custom-image:v1",
        )
        warm_task, _ = self._warm_run(
            branch="main",
            extra_state={
                "sandbox_environment_id": str(sandbox_environment.id),
                "custom_image_id": str(custom_image.id),
            },
        )
        with patch(f"{TITLE_SRC}.generate_task_title", return_value="T"):
            dto = self._create(
                branch="feature/x",
                sandbox_environment_id=sandbox_environment.id,
                custom_image_id=custom_image.id,
            )

        assert str(dto.id) != str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 2

    def test_revoked_environment_does_not_reuse_warm_task(self):
        other_user = User.objects.create_and_join(self.organization, "other-create-owner@posthog.com", None)
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=other_user,
            name="Shared environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
            private=False,
        )
        warm_task, run = self._warm_run(extra_state={"sandbox_environment_id": str(sandbox_environment.id)})
        sandbox_environment.private = True
        sandbox_environment.save(update_fields=["private", "updated_at"])

        with (
            patch(f"{FACADE}.signal_task_run_user_message") as mock_signal,
            patch(f"{TITLE_SRC}.generate_task_title", return_value="T"),
        ):
            dto = self._create(sandbox_environment_id=sandbox_environment.id)

        assert str(dto.id) != str(warm_task.id)
        mock_signal.assert_not_called()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_terminal_warm_run_is_not_reused(self):
        warm_task, run = self._warm_run()
        run.status = TaskRun.Status.COMPLETED
        run.save(update_fields=["status"])
        with patch(f"{TITLE_SRC}.generate_task_title", return_value="T"):
            dto = self._create()

        assert str(dto.id) != str(warm_task.id)

    def test_local_submit_without_branch_key_never_reuses_a_warm(self):
        warm_task, _ = self._warm_run(branch=None)
        with patch(f"{TITLE_SRC}.generate_task_title", return_value="T"):
            dto = facade.create_task(
                self.team.id,
                self.user.id,
                validated_data={"description": "local task", "repository": "posthog/posthog"},
            )

        assert str(dto.id) != str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 2

    def test_forwards_pending_message_and_run_artifacts_on_warm_reuse(self):
        warm_task, run = self._warm_run()
        run.artifacts = [_artifact_entry("artifact-1")]
        run.save(update_fields=["artifacts"])

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            dto = self._create(
                description="/millie readme this skill",
                pending_user_message='<skill name="millie" source="user" /> readme this skill',
                pending_user_artifact_ids=["artifact-1"],
            )

        assert str(dto.id) == str(warm_task.id)
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == '<skill name="millie" source="user" /> readme this skill'
        assert kwargs["artifact_ids"] == ["artifact-1"]
        warm_task.refresh_from_db()
        assert warm_task.description == "/millie readme this skill"

    def test_does_not_persist_augmented_pending_message_when_description_empty(self):
        warm_task, _ = self._warm_run()
        augmented_message = "<channel_context>\nUse this workspace context.\n</channel_context>"

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            dto = self._create(description="", pending_user_message=augmented_message)

        assert str(dto.id) == str(warm_task.id)
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == augmented_message
        warm_task.refresh_from_db()
        assert warm_task.description == ""

    def test_skips_warm_reuse_when_pending_artifacts_missing_from_warm_run(self):
        warm_task, run = self._warm_run()
        with (
            patch(f"{FACADE}.signal_task_run_user_message") as m_signal,
            patch(f"{TITLE_SRC}.generate_task_title", return_value="T"),
        ):
            dto = self._create(pending_user_artifact_ids=["not-uploaded"])

        assert str(dto.id) != str(warm_task.id)
        m_signal.assert_not_called()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_create_endpoint_passes_pending_fields_to_warm_activation(self):
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Custom environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        custom_image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name="Custom image",
            status=SandboxCustomImage.Status.READY,
            modal_image_name="custom-image:v1",
        )
        warm_task, run = self._warm_run(
            extra_state={
                "sandbox_environment_id": str(sandbox_environment.id),
                "custom_image_id": str(custom_image.id),
            }
        )
        run.artifacts = [_artifact_entry("artifact-1")]
        run.save(update_fields=["artifacts"])

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            response = self.client.post(
                "/api/projects/@current/tasks/",
                {
                    "description": "/millie readme this skill",
                    "repository": "posthog/posthog",
                    "github_integration": self.integration.id,
                    "branch": "main",
                    "pending_user_message": "resolved skill message",
                    "pending_user_artifact_ids": ["artifact-1"],
                    "sandbox_environment_id": str(sandbox_environment.id),
                    "custom_image_id": str(custom_image.id),
                },
                format="json",
            )

        assert response.status_code == 201, response.content
        assert response.json()["id"] == str(warm_task.id)
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == "resolved skill message"
        assert kwargs["artifact_ids"] == ["artifact-1"]

    def test_create_endpoint_regates_a_warm_reuse_that_would_activate_a_sandbox(self):
        # Activating a warm starts the agent from the create endpoint, so the client never calls the run
        # endpoint that normally applies this gate. A warm booted while the caller was entitled must not
        # still run after entitlement is withdrawn.
        _warm_task, run = self._warm_run()

        with (
            patch(
                "products.tasks.backend.logic.services.code_usage_gate.get_desktop_access_decision",
                return_value=tasks_access.DesktopAccessDecision.STARTUP_PLAN,
            ),
            patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal,
        ):
            response = self.client.post(
                "/api/projects/@current/tasks/",
                {
                    "description": "fix the bug",
                    "repository": "posthog/posthog",
                    "github_integration": self.integration.id,
                    "branch": "main",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        m_signal.assert_not_called()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_create_endpoint_without_warm_hints_is_not_regated(self):
        # Only a create that can activate a sandbox takes the run-start gates; a plain create still
        # goes through, and the run endpoint gates it when execution is actually requested.
        with patch(
            "products.tasks.backend.logic.services.code_usage_gate.get_desktop_access_decision",
            return_value=tasks_access.DesktopAccessDecision.STARTUP_PLAN,
        ):
            response = self.client.post(
                "/api/projects/@current/tasks/",
                {"description": "fix the bug"},
                format="json",
            )

        assert response.status_code == 201, response.content


class TestWarmRunRelease(APIBaseTest):
    """Handing a warm sandbox back must never stop a run that has already been activated."""

    def setUp(self) -> None:
        super().setUp()
        _allow_desktop_access(self)
        self.task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )

    def _run(self, *, awaiting: bool) -> TaskRun:
        return self.task.create_run(
            mode="interactive",
            extra_state={"prewarmed": True, **({"await_user_message": True} if awaiting else {})},
        )

    def _release(self, run: TaskRun):
        return self.client.post(
            f"/api/projects/@current/tasks/{self.task.id}/runs/{run.id}/cancel/",
            {"only_if_awaiting_first_message": True},
            format="json",
        )

    @parameterized.expand(
        [
            # One warm Run is shared by every composer holding the same selection, so a composer that
            # releases after another one submitted would otherwise stop the run that submit started.
            ("activated_run_is_left_alone", False, status.HTTP_200_OK, False),
            # And the fence must not turn every release into a no-op, or abandoned sandboxes pile up
            # in the warm pool until the reaper takes them.
            ("idling_warm_is_still_stopped", True, status.HTTP_202_ACCEPTED, True),
        ]
    )
    def test_release_only_stops_a_run_still_awaiting_its_first_message(
        self, _case_name, awaiting, expected_status, expect_signal
    ):
        run = self._run(awaiting=awaiting)

        with patch(
            "products.tasks.backend.facade.cancellation._signal_complete_task", return_value="signaled"
        ) as m_signal:
            response = self._release(run)

        assert response.status_code == expected_status, response.content
        assert m_signal.called is expect_signal


class TestWarmTaskResumeSandbox(APIBaseTest):
    def test_warms_and_activates_a_successor_for_the_latest_terminal_run(self):
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        terminal = task.create_run(
            mode="interactive",
            branch="main",
            extra_state={
                "snapshot_external_id": "snapshot-1",
                "pr_base_branch": "main",
                "auto_publish": True,
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "initial_permission_mode": "plan",
            },
        )
        terminal.status = TaskRun.Status.CANCELLED
        terminal.save(update_fields=["status"])

        with (
            patch("products.tasks.backend.logic.services.warm.is_team_limited", return_value=False),
            patch("products.tasks.backend.logic.services.warm.execute_task_processing_workflow") as execute_workflow,
            self.captureOnCommitCallbacks(execute=True),
        ):
            warmed = facade.warm_task_resume_sandbox(
                task.id,
                self.team.id,
                self.user.id,
                resume_from_run_id=terminal.id,
                runtime_adapter="claude",
                model="claude-sonnet-5",
                reasoning_effort="high",
                initial_permission_mode="plan",
            )

        assert warmed is not None
        warm_run = TaskRun.objects.get(id=warmed.run_id)
        assert warm_run.state["resume_from_run_id"] == str(terminal.id)
        assert warm_run.state["snapshot_external_id"] == "snapshot-1"
        assert warm_run.state["await_user_message"] is True
        assert warm_run.state["auto_publish"] is True
        assert warm_run.state["pr_authorship_mode"] == "bot"
        execute_workflow.assert_called_once()
        assert execute_workflow.call_args.kwargs.get("create_pr", True) is True

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "resume_from_run_id": terminal.id,
                    "runtime_adapter": "claude",
                    "model": "claude-sonnet-5",
                    "reasoning_effort": "high",
                    "initial_permission_mode": "plan",
                    "pending_user_message": "continue",
                },
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 2
        signal.assert_called_once()
        warm_run.refresh_from_db()
        assert "await_user_message" not in warm_run.state

    def _terminal_run(self, task: Task) -> TaskRun:
        terminal = task.create_run(
            mode="interactive",
            branch="main",
            extra_state={
                "pr_base_branch": "main",
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "initial_permission_mode": "plan",
            },
        )
        terminal.status = TaskRun.Status.CANCELLED
        terminal.save(update_fields=["status"])
        return terminal

    def _warm_resume(self, task: Task, terminal: TaskRun):
        with (
            patch("products.tasks.backend.logic.services.warm.is_team_limited", return_value=False),
            patch("products.tasks.backend.logic.services.warm.execute_task_processing_workflow"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return facade.warm_task_resume_sandbox(
                task.id,
                self.team.id,
                self.user.id,
                resume_from_run_id=terminal.id,
                runtime_adapter="claude",
                model="claude-sonnet-5",
                initial_permission_mode="plan",
            )

    def test_warms_again_after_a_successor_is_released(self):
        # A released successor is terminal and sits in front of its own source, so a source fence that
        # only accepts the source or a live warm would leave the task unable to warm for the rest of
        # its life — and releases are routine: an emptied draft, a changed model, leaving the composer.
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        terminal = self._terminal_run(task)

        first = self._warm_resume(task, terminal)
        assert first is not None
        released = TaskRun.objects.get(id=first.run_id)
        released.status = TaskRun.Status.CANCELLED
        released.save(update_fields=["status"])

        second = self._warm_resume(task, terminal)

        assert second is not None
        assert second.run_id != first.run_id
        # The replacement resumes from the original terminal run, not from the successor handed back.
        assert TaskRun.objects.get(id=second.run_id).state["resume_from_run_id"] == str(terminal.id)

    def test_does_not_warm_from_a_source_the_task_has_moved_past(self):
        # The relaxation above must not become a wildcard: a terminal run that is not a released
        # successor of the named source still means the task moved on.
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        terminal = self._terminal_run(task)
        self._terminal_run(task)

        assert self._warm_resume(task, terminal) is None

    def test_does_not_warm_a_resume_source_from_a_previous_task_owner(self):
        # A handed-off task re-stamps its ownership version but leaves old runs on the previous one.
        # create_run rejects that stale resume source, so this best-effort endpoint must skip warming
        # rather than raise the ownership error on every debounced keystroke of the new owner.
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.POSTHOG_AI,
            created_by=self.user,
        )
        terminal = self._terminal_run(task)
        task.state = {**(task.state or {}), TASK_OWNERSHIP_VERSION_STATE_KEY: "handed-off"}
        task.save(update_fields=["state"])

        assert self._warm_resume(task, terminal) is None


class TestRunTaskWarmActivation(APIBaseTest):
    """The normal run path activates an idling warm Run instead of dispatching a fresh workflow."""

    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})

    def _warm_run(self, *, branch="main", extra_state: dict[str, Any] | None = None) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            repository="posthog/posthog",
            github_integration=self.integration,
        )
        run = task.create_run(
            mode="interactive",
            extra_state={"await_user_message": True, "branch": branch, **(extra_state or {})},
            branch=branch,
        )
        return task, run

    def test_activates_idling_warm_run_without_creating_a_new_run(self):
        task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do the thing",
                    "auto_publish": True,
                },
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 1
        m_signal.assert_called_once()
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == "do the thing"
        run.refresh_from_db()
        assert "await_user_message" not in run.state
        assert run.state.get("auto_publish") is True

    def test_falls_back_to_description_when_no_pending_message(self):
        task, run = self._warm_run()
        task.description = "from description"
        task.save(update_fields=["description"])
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            facade.run_task(
                task.id, self.team.id, self.user.id, validated_data={"mode": "interactive", "branch": "main"}
            )

        _, kwargs = m_signal.call_args
        assert kwargs["content"] == "from description"

    def test_materializes_staged_artifacts_onto_warm_run_before_activation(self):
        task, run = self._warm_run()
        TaskRun.update_state_atomic(run.id, updates={"reasoning_effort": "high"})
        staged = _artifact_entry("artifact-1")
        get_tasks_cache().set(build_task_staged_artifact_cache_key(str(task.id), "artifact-1"), staged, timeout=60)

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "pending_user_artifact_ids": ["artifact-1"],
                    "reasoning_effort": "xhigh",
                },
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 1
        run.refresh_from_db()
        assert [artifact["id"] for artifact in run.artifacts] == ["artifact-1"]
        assert "await_user_message" not in run.state
        assert run.state.get("reasoning_effort") == "xhigh"
        _, kwargs = m_signal.call_args
        assert kwargs["artifact_ids"] == ["artifact-1"]

    def test_missing_staged_artifacts_skip_warm_activation(self):
        task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message") as m_signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "pending_user_artifact_ids": ["ghost"],
                },
            )

        m_signal.assert_not_called()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True
        assert result is not None and result.error is not None
        assert task.runs.count() == 1

    def test_branch_mismatch_does_not_activate_warm_run(self):
        # Requesting a different branch than the warm Run was provisioned on must NOT activate it
        # (it would work the wrong branch); fall through to the cold path instead.
        task, run = self._warm_run(branch="main")
        with (
            patch(f"{FACADE}.signal_task_run_user_message") as m_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as m_trigger,
        ):
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "branch": "feature/x", "pending_user_message": "do it"},
            )

        m_signal.assert_not_called()
        m_trigger.assert_called_once()  # cold path: a fresh run was created + dispatched
        assert task.runs.count() == 2
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True  # warm run untouched

    def test_resume_successor_is_not_activated_for_a_run_that_asks_for_no_resume(self):
        # A successor's filesystem was restored from the run it resumes, so handing it to a request
        # that named no resume source would silently start "fresh" work on inherited state.
        task, predecessor = self._warm_run()
        predecessor.status = TaskRun.Status.CANCELLED
        predecessor.save(update_fields=["status"])
        run = task.create_run(
            mode="interactive",
            extra_state={
                "await_user_message": True,
                "branch": "main",
                "resume_from_run_id": str(predecessor.id),
            },
            branch="main",
        )
        with (
            patch(f"{FACADE}.signal_task_run_user_message") as m_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as m_trigger,
        ):
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "branch": "main", "pending_user_message": "do it"},
            )

        m_signal.assert_not_called()
        m_trigger.assert_called_once()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_sandbox_environment_mismatch_does_not_activate_warm_run(self):
        warm_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Warm environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        requested_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Requested environment",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.FULL,
        )
        task, run = self._warm_run(extra_state={"sandbox_environment_id": str(warm_environment.id)})

        with (
            patch(f"{FACADE}.signal_task_run_user_message") as mock_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as mock_trigger,
        ):
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "sandbox_environment_id": requested_environment.id,
                },
            )

        mock_signal.assert_not_called()
        mock_trigger.assert_called_once()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_context_window_mismatch_does_not_activate_warm_run(self):
        task, run = self._warm_run()
        with (
            patch(f"{FACADE}.signal_task_run_user_message") as mock_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as mock_trigger,
        ):
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "context_window": "1m",
                },
            )

        mock_signal.assert_not_called()
        mock_trigger.assert_called_once()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_fast_mode_mismatch_does_not_activate_warm_run(self):
        task, run = self._warm_run()
        with (
            patch(f"{FACADE}.signal_task_run_user_message") as mock_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as mock_trigger,
        ):
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "fast_mode": True,
                },
            )

        mock_signal.assert_not_called()
        mock_trigger.assert_called_once()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_matching_context_window_and_fast_mode_activates_warm_run(self):
        task, run = self._warm_run(extra_state={"context_window": "1m", "fast_mode": True})
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "context_window": "1m",
                    "fast_mode": True,
                },
            )

        m_signal.assert_called_once()
        run.refresh_from_db()
        assert "await_user_message" not in run.state

    def test_unready_custom_image_does_not_activate_warm_run(self):
        custom_image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            created_by=self.user,
            name="Custom image",
            status=SandboxCustomImage.Status.READY,
            modal_image_name="custom-image:v1",
        )
        task, run = self._warm_run(extra_state={"custom_image_id": str(custom_image.id)})
        custom_image.status = SandboxCustomImage.Status.ARCHIVED
        custom_image.save(update_fields=["status", "updated_at"])

        with (
            patch(f"{FACADE}.signal_task_run_user_message") as mock_signal,
            patch(f"{FACADE}._trigger_task_processing_workflow") as mock_trigger,
        ):
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={
                    "mode": "interactive",
                    "branch": "main",
                    "pending_user_message": "do it",
                    "custom_image_id": custom_image.id,
                },
            )

        mock_signal.assert_not_called()
        mock_trigger.assert_not_called()
        assert result is not None and result.error is not None
        assert "not ready" in result.error.detail
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True

    def test_explicit_resume_does_not_trigger_warm_activation(self):
        task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message") as m_signal:
            facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "resume_from_run_id": str(run.id)},
            )
        m_signal.assert_not_called()

    def test_other_team_member_cannot_activate_a_users_warm_run(self):
        # A USER_CREATED warm run is private to its creator. The task-visibility gate in run_task
        # must block a different team member before activation, so they cannot push the first message
        # into another user's already-running, credential-bearing warm sandbox.
        other = User.objects.create_and_join(self.organization, "other-warm@posthog.com", None)
        task, run = self._warm_run(branch="main")
        with patch(f"{FACADE}.signal_task_run_user_message") as m_signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                other.id,
                validated_data={"mode": "interactive", "branch": "main", "pending_user_message": "do it"},
            )

        assert result is None  # task not visible -> 404, no activation
        m_signal.assert_not_called()
        run.refresh_from_db()
        assert run.state.get("await_user_message") is True  # warm run untouched
