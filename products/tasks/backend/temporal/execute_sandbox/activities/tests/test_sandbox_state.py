import uuid

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.temporal.execute_sandbox.activities.sandbox_state import (
    SANDBOX_ID_STATE_KEY,
    ClearPersistedSandboxIdInput,
    PersistSandboxIdInput,
    ReadPersistedSandboxIdInput,
    clear_persisted_sandbox_id,
    persist_sandbox_id,
    read_persisted_sandbox_id,
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


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestReadPersistedSandboxId:
    def test_returns_persisted_value(self, activity_environment, test_task_run):
        test_task_run.state = {SANDBOX_ID_STATE_KEY: "sb-abc"}
        test_task_run.save(update_fields=["state"])

        result = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id,
            ReadPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        assert result.sandbox_id == "sb-abc"

    def test_returns_none_when_key_missing(self, activity_environment, test_task_run):
        result = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id,
            ReadPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        assert result.sandbox_id is None

    def test_returns_none_when_task_run_missing(self, activity_environment):
        missing_run_id = str(uuid.uuid4())

        result = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id,
            ReadPersistedSandboxIdInput(run_id=missing_run_id),
        )

        assert result.sandbox_id is None

    @pytest.mark.parametrize("bogus_value", [123, "", None, [], {}])
    def test_returns_none_when_persisted_value_is_not_a_nonempty_string(
        self, activity_environment, test_task_run, bogus_value
    ):
        # The activity defensively narrows the persisted value to "non-empty
        # string or None" — any other JSON-serializable shape that may have
        # crept in (older state, manual edits, deserialization quirks) should
        # be treated as if no sandbox was recorded so the reaper doesn't try
        # to destroy a garbage id.
        test_task_run.state = {SANDBOX_ID_STATE_KEY: bogus_value}
        test_task_run.save(update_fields=["state"])

        result = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id,
            ReadPersistedSandboxIdInput(run_id=str(test_task_run.id)),
        )

        assert result.sandbox_id is None


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestPersistClearReadRoundTrip:
    def test_persist_then_read_then_clear_then_read(self, activity_environment, test_task_run):
        run_id = str(test_task_run.id)

        async_to_sync(activity_environment.run)(
            persist_sandbox_id, PersistSandboxIdInput(run_id=run_id, sandbox_id="sb-rt")
        )
        after_persist = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id, ReadPersistedSandboxIdInput(run_id=run_id)
        )
        async_to_sync(activity_environment.run)(clear_persisted_sandbox_id, ClearPersistedSandboxIdInput(run_id=run_id))
        after_clear = async_to_sync(activity_environment.run)(
            read_persisted_sandbox_id, ReadPersistedSandboxIdInput(run_id=run_id)
        )

        assert after_persist.sandbox_id == "sb-rt"
        assert after_clear.sandbox_id is None
