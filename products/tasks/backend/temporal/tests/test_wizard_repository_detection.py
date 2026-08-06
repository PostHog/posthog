from dataclasses import dataclass, field

import pytest

from django.test import SimpleTestCase

from products.tasks.backend.constants import WIZARD_REPOSITORY_DETECTION_PROGRAMS
from products.tasks.backend.temporal import wizard_repository_detection as wizard_repository_detection_module
from products.tasks.backend.temporal.wizard_repository_detection import (
    RunWizardRepositoryDetectionInput,
    WizardRepositoryDetectionInput,
    WizardRepositoryDetectionWorkflow,
    _build_wizard_repository_detection_command,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    create_sandbox_for_repository,
    get_task_processing_context,
    prepare_sandbox_for_repository,
    run_wizard_repository_detection,
    update_task_run_status,
)


class TestBuildDetectionCommand(SimpleTestCase):
    def test_registered_kind_builds_subcommand_before_flags_without_headless(self) -> None:
        # yargs rejects the headless flag (only the base command declares it), and --repository
        # must be explicit because the sandbox clone's origin remote carries a token URL.
        command = _build_wizard_repository_detection_command(
            "error-tracking-source-maps", "/tmp/workspace/repos/acme/app", 123, "acme/app"
        )

        assert "upload-source-maps --detect-only" in command
        assert "--repository acme/app" in command
        assert "--headless-DONOTUSE-EXPERIMENTAL" not in command
        assert "--api-key" not in command
        assert command.index("upload-source-maps") < command.index("--install-dir")
        assert "--project-id 123" in command

    def test_every_registered_kind_maps_to_a_subcommand(self) -> None:
        # A registry entry whose args accidentally start with a flag would run the default
        # interactive TUI flow in the sandbox and hang until the timeout.
        for kind, program in WIZARD_REPOSITORY_DETECTION_PROGRAMS.items():
            assert program, kind
            assert not program[0].startswith("-"), kind

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            _build_wizard_repository_detection_command("no-such-kind", "/tmp/workspace/repos/a/b", 1, "a/b")


@dataclass
class _FakeContext:
    repository: str | None = "acme/app"
    wizard_config: dict | None = field(default_factory=lambda: {"kind": "error-tracking-source-maps"})


@dataclass
class _FakePrepared:
    github_token: str = "gh-token"
    shallow_clone: bool = True
    used_snapshot: bool = False


@dataclass
class _FakeCreated:
    sandbox_id: str = "sandbox-123"
    sandbox_url: str = "https://sandbox.example"
    connect_token: str | None = "connect-token"
    used_snapshot: bool | None = None


class TestDetectRepositoryWorkflow:
    def _install_fake_activities(
        self, monkeypatch, *, detection_error: Exception | None = None, context_error: Exception | None = None
    ):
        """Replace workflow.execute_activity with a dispatch table; returns the call log."""
        calls: list[tuple[object, object]] = []

        async def fake_execute_activity(activity_fn, activity_input, **kwargs):
            calls.append((activity_fn, activity_input))
            if activity_fn is get_task_processing_context:
                if context_error is not None:
                    raise context_error
                return _FakeContext()
            if activity_fn is prepare_sandbox_for_repository:
                return _FakePrepared()
            if activity_fn is create_sandbox_for_repository:
                return _FakeCreated()
            if activity_fn is run_wizard_repository_detection and detection_error is not None:
                raise detection_error
            return None

        monkeypatch.setattr(wizard_repository_detection_module.workflow, "execute_activity", fake_execute_activity)
        return calls

    async def test_happy_path_runs_the_full_sequence_and_completes_the_run(self, monkeypatch):
        calls = self._install_fake_activities(monkeypatch)

        result = await WizardRepositoryDetectionWorkflow().run(WizardRepositoryDetectionInput(run_id="run-id"))

        assert result.success is True
        assert result.sandbox_id == "sandbox-123"
        assert [fn for fn, _ in calls] == [
            get_task_processing_context,
            update_task_run_status,  # in_progress
            prepare_sandbox_for_repository,
            create_sandbox_for_repository,
            clone_repository_in_sandbox,
            run_wizard_repository_detection,
            update_task_run_status,  # completed
            cleanup_sandbox,
        ]
        detection_input = next(inp for fn, inp in calls if fn is run_wizard_repository_detection)
        assert isinstance(detection_input, RunWizardRepositoryDetectionInput)
        assert detection_input.repository == "acme/app"
        statuses = [inp.status for fn, inp in calls if fn is update_task_run_status]
        assert statuses == ["in_progress", "completed"]

    async def test_detection_failure_marks_run_failed_and_still_cleans_up(self, monkeypatch):
        # The two regressions this workflow must never ship: a leaked sandbox (cleanup skipped
        # on failure) and a run orphaned in in_progress (no terminal status written).
        calls = self._install_fake_activities(monkeypatch, detection_error=RuntimeError("scan exploded"))

        result = await WizardRepositoryDetectionWorkflow().run(WizardRepositoryDetectionInput(run_id="run-id"))

        assert result.success is False
        assert result.error is not None and "scan exploded" in result.error
        assert calls[-1][0] is cleanup_sandbox
        assert calls[-1][1].sandbox_id == "sandbox-123"
        statuses = [inp.status for fn, inp in calls if fn is update_task_run_status]
        assert statuses == ["in_progress", "failed"]

    async def test_context_failure_marks_run_failed_instead_of_orphaning_it(self, monkeypatch):
        # A context failure raised outside the try would escape the workflow and leave the run
        # in QUEUED with no error until the 24h killer sweeps it.
        calls = self._install_fake_activities(monkeypatch, context_error=RuntimeError("run row not ready"))

        result = await WizardRepositoryDetectionWorkflow().run(WizardRepositoryDetectionInput(run_id="run-id"))

        assert result.success is False
        assert result.error is not None and "run row not ready" in result.error
        statuses = [inp.status for fn, inp in calls if fn is update_task_run_status]
        assert statuses == ["failed"]
        assert prepare_sandbox_for_repository not in [fn for fn, _ in calls]

    async def test_missing_repository_fails_without_provisioning(self, monkeypatch):
        calls = self._install_fake_activities(monkeypatch)

        async def fake_execute_activity_no_repo(activity_fn, activity_input, **kwargs):
            calls.append((activity_fn, activity_input))
            if activity_fn is get_task_processing_context:
                return _FakeContext(repository=None)
            return None

        monkeypatch.setattr(
            wizard_repository_detection_module.workflow, "execute_activity", fake_execute_activity_no_repo
        )

        result = await WizardRepositoryDetectionWorkflow().run(WizardRepositoryDetectionInput(run_id="run-id"))

        assert result.success is False
        assert prepare_sandbox_for_repository not in [fn for fn, _ in calls]
        assert cleanup_sandbox not in [fn for fn, _ in calls]


# Same pytest-asyncio setup as the process_task workflow unit tests.
pytestmark = pytest.mark.asyncio
