import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.temporal.execute_sandbox.activities.sandbox_state import (
    SANDBOX_ID_STATE_KEY,
    ClearPersistedSandboxIdInput,
    PersistSandboxIdInput,
    clear_persisted_sandbox_id,
    persist_sandbox_id,
)


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestPersistSandboxId:
    def test_writes_sandbox_id_to_state(self, activity_environment, test_task_run):
        async_to_sync(activity_environment.run)(
            persist_sandbox_id,
            PersistSandboxIdInput(run_id=str(test_task_run.id), sandbox_id="sb-123"),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state[SANDBOX_ID_STATE_KEY] == "sb-123"

    def test_preserves_other_state_keys(self, activity_environment, test_task_run):
        test_task_run.state = {"mode": "background", "pending_user_message": "hi"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            persist_sandbox_id,
            PersistSandboxIdInput(run_id=str(test_task_run.id), sandbox_id="sb-456"),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state == {
            "mode": "background",
            "pending_user_message": "hi",
            SANDBOX_ID_STATE_KEY: "sb-456",
        }

    def test_overwrites_existing_sandbox_id(self, activity_environment, test_task_run):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-old"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            persist_sandbox_id,
            PersistSandboxIdInput(run_id=str(test_task_run.id), sandbox_id="sb-new"),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state[SANDBOX_ID_STATE_KEY] == "sb-new"


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestClearPersistedSandboxId:
    def test_removes_sandbox_id_key(self, activity_environment, test_task_run):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-123", "mode": "background"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            clear_persisted_sandbox_id,
            ClearPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        test_task_run.refresh_from_db()
        assert SANDBOX_ID_STATE_KEY not in test_task_run.state
        assert test_task_run.state == {"mode": "background"}

    def test_noop_when_key_absent(self, activity_environment, test_task_run):
        test_task_run.state = {"mode": "background"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            clear_persisted_sandbox_id,
            ClearPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state == {"mode": "background"}
