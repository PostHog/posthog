import uuid

import pytest
from unittest.mock import patch

from django.db import OperationalError

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError

from products.tasks.backend.temporal.task_management.activities import pending_followups as pending_module
from products.tasks.backend.temporal.task_management.activities.pending_followups import (
    CI_IDLE_SKIPS_STATE_KEY,
    CI_WAIT_CHECKS_STATE_KEY,
    PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY,
    PENDING_FOLLOWUPS_GENERATION_STATE_KEY,
    PENDING_FOLLOWUPS_STATE_KEY,
    TASK_RUN_NOT_FOUND_ERROR_TYPE,
    PersistPendingFollowupsInput,
    PersistPendingFollowupsV2Input,
    ReadPendingFollowupsInput,
    persist_pending_followups,
    persist_pending_followups_v2,
    persist_pending_followups_v3,
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

    @pytest.mark.parametrize("persist", [persist_pending_followups_v2, persist_pending_followups_v3])
    def test_older_generation_cannot_overwrite_newer_queue(self, activity_environment, test_task_run, persist):
        run_id = str(test_task_run.id)
        first = [{"message": "first", "artifact_ids": [], "source": "user", "sequence": 1}]
        complete = [
            *first,
            {"message": "second", "artifact_ids": [], "source": "user", "sequence": 2},
        ]

        for generation, followups in [(1, first), (2, complete), (1, first)]:
            async_to_sync(activity_environment.run)(
                persist,
                PersistPendingFollowupsV2Input(
                    run_id=run_id,
                    followups=followups,
                    generation=generation,
                    ci_idle_skips=generation,
                    ci_wait_checks=generation,
                ),
            )
        async_to_sync(activity_environment.run)(
            persist_pending_followups,
            PersistPendingFollowupsInput(run_id=run_id, followups=first),
        )

        test_task_run.refresh_from_db()
        assert test_task_run.state[PENDING_FOLLOWUPS_STATE_KEY] == complete
        assert test_task_run.state[PENDING_FOLLOWUPS_GENERATION_STATE_KEY] == 2
        restored = async_to_sync(activity_environment.run)(
            read_pending_followups, ReadPendingFollowupsInput(run_id=run_id)
        )
        assert restored.ci_idle_skips == 2
        assert restored.ci_wait_checks == 2

    @pytest.mark.parametrize("persist", [persist_pending_followups_v2, persist_pending_followups_v3])
    def test_missing_task_run_is_non_retryable(self, activity_environment, persist):
        with pytest.raises(ApplicationError) as exc_info:
            async_to_sync(activity_environment.run)(
                persist,
                PersistPendingFollowupsV2Input(
                    run_id=str(uuid.uuid4()),
                    followups=[],
                    generation=1,
                ),
            )

        assert exc_info.value.type == TASK_RUN_NOT_FOUND_ERROR_TYPE
        assert exc_info.value.non_retryable is True

    @pytest.mark.parametrize("before,after", [((2, 96), (0, 0)), ((1, 95), (2, 96))])
    @pytest.mark.parametrize("newer_write", [None, persist_pending_followups_v2, persist_pending_followups_v3])
    def test_recovers_staged_counters_and_queue_after_failed_apply(
        self, activity_environment, test_task_run, before, after, newer_write
    ):
        test_task_run.state = {
            CI_IDLE_SKIPS_STATE_KEY: before[0],
            CI_WAIT_CHECKS_STATE_KEY: before[1],
            PENDING_FOLLOWUPS_GENERATION_STATE_KEY: 1,
            "mode": "background",
        }
        test_task_run.save(update_fields=["state"])
        followups = [{"message": "retry queued work", "artifact_ids": [], "source": "user"}] if after == (0, 0) else []
        snapshot = PersistPendingFollowupsV2Input(
            run_id=str(test_task_run.id),
            followups=followups,
            generation=2,
            ci_idle_skips=after[0],
            ci_wait_checks=after[1],
        )
        with patch.object(
            pending_module, "_commit_pending_followups_checkpoint", side_effect=OperationalError("apply unavailable")
        ):
            for _ in range(3):
                with pytest.raises(OperationalError, match="apply unavailable"):
                    async_to_sync(activity_environment.run)(persist_pending_followups_v3, snapshot)

        legacy_read = async_to_sync(activity_environment.run)(
            read_pending_followups, ReadPendingFollowupsInput(run_id=str(test_task_run.id))
        )
        assert (legacy_read.ci_idle_skips, legacy_read.ci_wait_checks) == before
        test_task_run.refresh_from_db()
        assert test_task_run.state[PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY]["generation"] == 2

        if newer_write:
            async_to_sync(activity_environment.run)(
                newer_write,
                PersistPendingFollowupsV2Input(
                    run_id=str(test_task_run.id), followups=[], generation=3, ci_idle_skips=1, ci_wait_checks=4
                ),
            )
        restored = async_to_sync(activity_environment.run)(
            read_pending_followups, ReadPendingFollowupsInput(run_id=str(test_task_run.id), recover_checkpoint=True)
        )
        assert (restored.ci_idle_skips, restored.ci_wait_checks) == ((1, 4) if newer_write else after)
        assert restored.followups == ([] if newer_write else followups)
        test_task_run.refresh_from_db()
        assert PENDING_FOLLOWUPS_CHECKPOINT_STATE_KEY not in test_task_run.state
        assert test_task_run.state["mode"] == "background"
        async_to_sync(activity_environment.run)(persist_pending_followups_v3, snapshot)
        test_task_run.refresh_from_db()
        assert test_task_run.state[CI_IDLE_SKIPS_STATE_KEY] == restored.ci_idle_skips
        assert test_task_run.state[CI_WAIT_CHECKS_STATE_KEY] == restored.ci_wait_checks


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

    @pytest.mark.parametrize("ci_idle_skips", [None, 2, "invalid", -1, True])
    def test_returns_empty_when_key_missing(self, activity_environment, test_task_run, ci_idle_skips):
        if ci_idle_skips is not None:
            test_task_run.state = {
                CI_IDLE_SKIPS_STATE_KEY: ci_idle_skips,
                CI_WAIT_CHECKS_STATE_KEY: ci_idle_skips,
            }
            test_task_run.save(update_fields=["state"])
        result = async_to_sync(activity_environment.run)(
            read_pending_followups,
            ReadPendingFollowupsInput(run_id=str(test_task_run.id)),
        )

        assert result.followups == []
        assert result.ci_idle_skips == (2 if ci_idle_skips == 2 else 0)
        assert result.ci_wait_checks == (2 if ci_idle_skips == 2 else 0)

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
