from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import PermissionDenied, Throttled

from posthog.exceptions import QuotaLimitExceeded
from posthog.models import Integration, User

from products.tasks.backend.facade import (
    api as facade,
    contracts,
)
from products.tasks.backend.logic.services.staged_artifacts import (
    build_task_artifact_entry,
    build_task_staged_artifact_cache_key,
)
from products.tasks.backend.logic.services.warm import WarmResult
from products.tasks.backend.models import SandboxCustomImage, SandboxEnvironment, Task, TaskRun
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


class TestWarmTaskSandbox(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})

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

    @patch("products.tasks.backend.presentation.views.api.code_access_required_response", return_value=None)
    @patch("products.tasks.backend.presentation.views.api.TaskViewSet._warm_enabled", return_value=True)
    @patch("products.tasks.backend.facade.api.warm_task_sandbox")
    def test_warm_endpoint_forwards_sandbox_selection(self, mock_warm, _mock_warm_enabled, _mock_code_access):
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
        self.integration = Integration.objects.create(team=self.team, kind="github", config={})

    def _warm_run(
        self, *, repository="posthog/posthog", branch="main", created_by=None, extra_state: dict[str, Any] | None = None
    ) -> tuple[Task, TaskRun]:
        task = Task.objects.create(
            team=self.team,
            title="",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=created_by or self.user,
            repository=repository,
            github_integration=self.integration,
        )
        run = task.create_run(
            mode="interactive",
            extra_state={"await_user_message": True, "branch": branch, **(extra_state or {})},
            branch=branch,
        )
        return task, run

    def _create(self, **data):
        validated = {"description": "fix the bug", "repository": "posthog/posthog", "branch": "main"}
        validated.update(data)
        return facade.create_task(self.team.id, self.user.id, validated_data=validated)

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
                },
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 1
        run.refresh_from_db()
        assert [artifact["id"] for artifact in run.artifacts] == ["artifact-1"]
        assert "await_user_message" not in run.state
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
