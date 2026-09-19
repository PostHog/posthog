import uuid

import pytest
from unittest.mock import ANY, Mock, patch

from asgiref.sync import async_to_sync

from products.tasks.backend.exceptions import SandboxNotFoundError
from products.tasks.backend.logic.services.sandbox_usage import SandboxDestroyOutcome
from products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox import (
    ReapOrphanedSandboxInput,
    reap_orphaned_sandbox,
)
from products.tasks.backend.temporal.execute_sandbox.activities.sandbox_state import SANDBOX_ID_STATE_KEY

# Patch target — the reap module resolves the provider class per sandbox id, so
# patching the resolver at its import site is what intercepts the call.
SANDBOX_IMPORT_PATH = (
    "products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox.get_sandbox_class_for_sandbox_id"
)


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestReapOrphanedSandbox:
    def test_returns_none_when_no_persisted_id(self, activity_environment, test_task_run):
        with patch(SANDBOX_IMPORT_PATH) as sandbox_cls:
            result = async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        assert result.reaped_sandbox_id is None
        assert result.destroy_succeeded is True
        # Modal call must not happen when there's nothing to reap.
        sandbox_cls.return_value.get_by_id.assert_not_called()

    def test_returns_none_when_task_run_missing(self, activity_environment):
        with patch(SANDBOX_IMPORT_PATH) as sandbox_cls:
            result = async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(uuid.uuid4())),
            )

        assert result.reaped_sandbox_id is None
        sandbox_cls.return_value.get_by_id.assert_not_called()

    @pytest.mark.parametrize("bogus_value", [123, "", None, [], {}])
    def test_treats_non_string_persisted_value_as_no_sandbox(self, activity_environment, test_task_run, bogus_value):
        # Defensive narrowing: only a non-empty string in state should trigger
        # a Modal call. Anything else (older schemas, manual edits) is treated
        # as "nothing recorded" so we don't pass garbage to `Sandbox.get_by_id`.
        test_task_run.state = {SANDBOX_ID_STATE_KEY: bogus_value}
        test_task_run.save(update_fields=["state"])

        with patch(SANDBOX_IMPORT_PATH) as sandbox_cls:
            result = async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        assert result.reaped_sandbox_id is None
        sandbox_cls.return_value.get_by_id.assert_not_called()

    def test_destroys_and_clears_when_persisted_id_present(self, activity_environment, test_task_run):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-orphan", "mode": "background"}
        test_task_run.save(update_fields=["state"])

        with patch(SANDBOX_IMPORT_PATH) as sandbox_cls:
            destroy_mock = Mock()
            sandbox_cls.return_value.get_by_id.return_value = Mock(destroy=destroy_mock)

            result = async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        assert result.reaped_sandbox_id == "sb-orphan"
        assert result.destroy_succeeded is True
        sandbox_cls.return_value.get_by_id.assert_called_once_with("sb-orphan")
        destroy_mock.assert_called_once()

        test_task_run.refresh_from_db()
        # State key is cleared; other keys preserved.
        assert SANDBOX_ID_STATE_KEY not in test_task_run.state
        assert test_task_run.state == {"mode": "background"}

    def test_records_cpu_usage_before_destroy(self, activity_environment, test_task_run):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-orphan"}
        test_task_run.save(update_fields=["state"])

        with (
            patch(SANDBOX_IMPORT_PATH) as sandbox_cls,
            patch(
                "products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox.close_sandbox_session"
            ) as close_session,
        ):
            sandbox = sandbox_cls.return_value.get_by_id.return_value
            sandbox.read_cpu_usage_usec.return_value = 12_345_678
            sandbox.read_billed_cpu_usage_usec.return_value = 15_000_000

            async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        sandbox.read_cpu_usage_usec.assert_called_once_with()
        sandbox.destroy.assert_called_once_with()
        close_session.assert_called_once_with(
            "sb-orphan",
            reason="reaped",
            destroy_outcome=SandboxDestroyOutcome.SUCCEEDED,
            cpu_usage_usec=12_345_678,
            billed_cpu_usage_usec=15_000_000,
            cpu_usage_measured_at=ANY,
        )

    @pytest.mark.parametrize(
        "error,expected_outcome",
        [
            (RuntimeError("modal down"), SandboxDestroyOutcome.FAILED),
            (
                SandboxNotFoundError(
                    "Sandbox sb-gone not found",
                    {"sandbox_id": "sb-gone"},
                    cause=RuntimeError("not found"),
                ),
                SandboxDestroyOutcome.SANDBOX_NOT_FOUND,
            ),
        ],
    )
    def test_reports_destroy_outcome_for_failures(self, activity_environment, test_task_run, error, expected_outcome):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-gone"}
        test_task_run.save(update_fields=["state"])

        with (
            patch(SANDBOX_IMPORT_PATH) as sandbox_cls,
            patch(
                "products.tasks.backend.temporal.execute_sandbox.activities.reap_orphaned_sandbox.close_sandbox_session"
            ) as close_session,
        ):
            sandbox_cls.return_value.get_by_id.side_effect = error

            async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        assert close_session.call_args.kwargs["destroy_outcome"] == expected_outcome

    def test_clears_state_even_when_modal_destroy_fails(self, activity_environment, test_task_run):
        # If Modal destroy raises (sandbox already gone, transient API failure)
        # we must still clear the state key — Modal's per-sandbox TTL is the
        # backstop, and a stale id staying in state would just be re-reaped
        # on every subsequent start.
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-dead"}
        test_task_run.save(update_fields=["state"])

        with patch(SANDBOX_IMPORT_PATH) as sandbox_cls:
            sandbox_cls.return_value.get_by_id.side_effect = RuntimeError("modal down")

            result = async_to_sync(activity_environment.run)(
                reap_orphaned_sandbox,
                ReapOrphanedSandboxInput(run_id=str(test_task_run.id)),
            )

        assert result.reaped_sandbox_id == "sb-dead"
        assert result.destroy_succeeded is False

        test_task_run.refresh_from_db()
        assert SANDBOX_ID_STATE_KEY not in test_task_run.state
