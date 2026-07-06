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
from products.tasks.backend.models import Task, TaskRun
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

    def _warm_run(self, *, repository="posthog/posthog", branch="main", created_by=None) -> tuple[Task, TaskRun]:
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
            mode="interactive", extra_state={"await_user_message": True, "branch": branch}, branch=branch
        )
        return task, run

    def _create(self, **data):
        validated = {"description": "fix the bug", "repository": "posthog/posthog", "branch": "main"}
        validated.update(data)
        return facade.create_task(self.team.id, self.user.id, validated_data=validated)

    def test_reuses_matching_warm_task_and_activates_it_in_place(self):
        warm_task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            dto = self._create()

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

    def test_does_not_overwrite_existing_warm_description(self):
        warm_task, _ = self._warm_run()
        warm_task.description = "already there"
        warm_task.save(update_fields=["description"])

        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True):
            self._create(description="new prompt")
        warm_task.refresh_from_db()
        assert warm_task.description == "already there"

    def test_branch_mismatch_creates_a_new_cold_task(self):
        warm_task, _ = self._warm_run(branch="main")
        with patch(f"{TITLE_SRC}.generate_task_title", return_value="T"):
            dto = self._create(branch="feature/x")

        assert str(dto.id) != str(warm_task.id)
        assert Task.objects.filter(team=self.team, deleted=False).count() == 2

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
        warm_task, run = self._warm_run()
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

    def _warm_run(self, *, branch="main") -> tuple[Task, TaskRun]:
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
            mode="interactive", extra_state={"await_user_message": True, "branch": branch}, branch=branch
        )
        return task, run

    def test_activates_idling_warm_run_without_creating_a_new_run(self):
        task, run = self._warm_run()
        with patch(f"{FACADE}.signal_task_run_user_message", return_value=True) as m_signal:
            result = facade.run_task(
                task.id,
                self.team.id,
                self.user.id,
                validated_data={"mode": "interactive", "branch": "main", "pending_user_message": "do the thing"},
            )

        assert result is not None and result.error is None
        assert task.runs.count() == 1
        m_signal.assert_called_once()
        _, kwargs = m_signal.call_args
        assert kwargs["content"] == "do the thing"
        run.refresh_from_db()
        assert "await_user_message" not in run.state

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
