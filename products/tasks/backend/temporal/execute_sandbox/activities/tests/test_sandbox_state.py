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
    @pytest.mark.parametrize("sandbox_id", [None, "sb-123", "sb-replaced"])
    def test_removes_sandbox_id_key(self, activity_environment, test_task_run, sandbox_id):
        connection = {
            "sandbox_url": "https://sandbox.example.com/rpc",
            "sandbox_connect_token": "fake-token",
            "sandbox_jwt_kid": "fake-kid",
            "sandbox_backend": "modal",
        }
        test_task_run.state = {**connection, SANDBOX_ID_STATE_KEY: "sb-123", "mode": "background"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            clear_persisted_sandbox_id,
            ClearPersistedSandboxIdInput(run_id=str(test_task_run.id), sandbox_id=sandbox_id),
        )

        test_task_run.refresh_from_db()
        expected_state = {"mode": "background"}
        if sandbox_id != "sb-123":
            expected_state.update(connection)
        if sandbox_id == "sb-replaced":
            expected_state[SANDBOX_ID_STATE_KEY] = "sb-123"
        assert test_task_run.state == expected_state

    def test_noop_when_key_absent(self, activity_environment, test_task_run):
        test_task_run.state = {"mode": "background"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            clear_persisted_sandbox_id,
            ClearPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state == {"mode": "background"}
