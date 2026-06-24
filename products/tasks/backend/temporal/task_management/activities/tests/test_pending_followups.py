import uuid

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.temporal.task_management.activities.pending_followups import (
    PENDING_FOLLOWUPS_STATE_KEY,
    PersistPendingFollowupsInput,
    ReadPendingFollowupsInput,
    persist_pending_followups,
    read_pending_followups,
)


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestPersistPendingFollowups:
    def test_writes_list_to_state(self, activity_environment, test_task_run):
        payload = [
            {"message": "m1", "artifact_ids": [], "source": "user"},
            {"message": "m2", "artifact_ids": ["a1"], "source": "user"},
        ]
        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(run_id=str(test_task_run.id), followups=payload),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state[PENDING_FOLLOWUPS_STATE_KEY] == payload

    def test_empty_list_removes_state_key(self, activity_environment, test_task_run):
        # Empty list should mean "nothing queued" — remove the key entirely
        # so it doesn't accumulate stale `[]` values forever.
        test_task_run.state = {PENDING_FOLLOWUPS_STATE_KEY: [{"message": "old", "artifact_ids": [], "source": "user"}]}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(run_id=str(test_task_run.id), followups=[]),
        )

        test_task_run.refresh_from_db()
        assert PENDING_FOLLOWUPS_STATE_KEY not in test_task_run.state

    def test_preserves_unrelated_state_keys(self, activity_environment, test_task_run):
        test_task_run.state = {"mode": "background", "sandbox_id": "sb-1"}
        test_task_run.save(update_fields=["state"])

        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(
                run_id=str(test_task_run.id),
                followups=[{"message": "m", "artifact_ids": [], "source": "user"}],
            ),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state["mode"] == "background"
        assert test_task_run.state["sandbox_id"] == "sb-1"
        assert test_task_run.state[PENDING_FOLLOWUPS_STATE_KEY] == [
            {"message": "m", "artifact_ids": [], "source": "user"}
        ]


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestReadPendingFollowups:
    def test_returns_persisted_list(self, activity_environment, test_task_run):
        payload = [{"message": "m1", "artifact_ids": ["a1"], "source": "ci"}]
        test_task_run.state = {PENDING_FOLLOWUPS_STATE_KEY: payload}
        test_task_run.save(update_fields=["state"])

        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(test_task_run.id)),
        )

        assert result.followups == payload

    def test_returns_empty_when_key_missing(self, activity_environment, test_task_run):
        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(test_task_run.id)),
        )

        assert result.followups == []

    def test_returns_empty_when_task_run_missing(self, activity_environment):
        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(uuid.uuid4())),
        )

        assert result.followups == []

    @pytest.mark.parametrize("bogus_value", ["string-not-list", 42, {"oops": True}, None])
    def test_returns_empty_when_value_is_not_a_list(self, activity_environment, test_task_run, bogus_value):
        test_task_run.state = {PENDING_FOLLOWUPS_STATE_KEY: bogus_value}
        test_task_run.save(update_fields=["state"])

        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(test_task_run.id)),
        )

        assert result.followups == []

    def test_filters_out_non_dict_entries(self, activity_environment, test_task_run):
        # If state is partially malformed (older shape, manual edit), keep the
        # dict entries and drop the rest rather than crashing startup.
        test_task_run.state = {
            PENDING_FOLLOWUPS_STATE_KEY: [
                {"message": "good", "artifact_ids": [], "source": "user"},
                "string-not-followup",
                42,
                {"message": "also-good", "artifact_ids": [], "source": "user"},
            ]
        }
        test_task_run.save(update_fields=["state"])

        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(test_task_run.id)),
        )

        assert result.followups == [
            {"message": "good", "artifact_ids": [], "source": "user"},
            {"message": "also-good", "artifact_ids": [], "source": "user"},
        ]


@pytest.mark.requires_secrets
@pytest.mark.django_db(transaction=True)
class TestPersistReadRoundTrip:
    def test_persist_then_read(self, activity_environment, test_task_run):
        run_id = str(test_task_run.id)
        payload = [
            {"message": "m1", "artifact_ids": [], "source": "user"},
            {"message": "m2", "artifact_ids": ["a1"], "source": "ci"},
        ]

        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(run_id=run_id, followups=payload),
        )
        after_persist = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=run_id),
        )
        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(run_id=run_id, followups=[]),
        )
        after_clear = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=run_id),
        )

        assert after_persist.followups == payload
        assert after_clear.followups == []
