import uuid
import datetime as dt
import contextvars

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from posthog.exceptions_capture import ambient_exception_properties

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    TransientObjectStoreError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    RepartitionBudgetExceededError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    MAX_REPARTITION_ATTEMPTS,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
    _maybe_flag_pre_extraction,
    _maybe_repartition_table,
    _rewrite_deadline,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table"

TEAM_ID = 1
SCHEMA_ID = str(uuid.uuid4())
JOB_ID = str(uuid.uuid4())
SOURCE_ID = str(uuid.uuid4())

PENDING_TARGET = {
    "partition_mode": "datetime",
    "partition_format": "day",
    "partition_count": None,
    "partition_size": None,
    "partition_keys": ["created_at"],
    "trigger_reason": "proactive_threshold",
    "attempts": 0,
}


def _schema(
    *,
    name: str,
    s3_folder_name: str | None,
    pending: dict | None = PENDING_TARGET,
    swap: dict | None = None,
    rewrite: dict | None = None,
) -> MagicMock:
    schema = MagicMock()
    schema.id = SCHEMA_ID
    schema.name = name
    schema.s3_folder_name = s3_folder_name
    schema.resolved_s3_folder_name = s3_folder_name
    schema.team_id = TEAM_ID
    schema.delta_revive_required = None
    schema.repartition_swap = swap
    schema.repartition_pending = pending
    schema.repartition_rewrite = rewrite
    # The failure bookkeeping re-reads the claim to check it still owns the schema, so the mock has
    # to actually remember the token the activity just staked.
    schema.set_repartition_claim.side_effect = lambda claim: setattr(schema, "repartition_claim", claim)
    # Same for the pending marker: the attempt is charged before the rewrite and refunded after, and
    # the refund only fires when it reads back the count it wrote.
    schema.set_repartition_pending.side_effect = lambda p: setattr(schema, "repartition_pending", p)
    return schema


class TestRepartitionActivityDeltaFolder:
    @pytest.mark.parametrize(
        "name, s3_folder_name, expected_resource_name",
        [
            ("public.posthog_externaldatajob", "posthog_externaldatajob", "posthog_externaldatajob"),
            ("stripe_charge", None, "stripe_charge"),
        ],
        ids=["folder_pinned_by_multi_schema_rename", "folder_derived_from_name"],
    )
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_repartitions_the_folder_the_pipeline_wrote_to(
        self,
        mock_schema_model: MagicMock,
        mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture: MagicMock,
        name: str,
        s3_folder_name: str | None,
        expected_resource_name: str,
    ) -> None:
        schema = _schema(name=name, s3_folder_name=s3_folder_name)
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.return_value = {"outcome": "completed"}

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        assert mock_helper_cls.call_args.kwargs["resource_name"] == expected_resource_name
        assert mock_repartition.await_count == 1
        await_args = mock_repartition.await_args
        assert await_args is not None
        assert await_args.kwargs["table_ref"] is mock_helper_cls.return_value
        assert mock_job_model.objects.get.call_args.kwargs == {"id": JOB_ID}


class TestJobContextBinding:
    """The import activity tags every captured exception with the sync's source/schema identity
    (`warehouse_sources_*` properties) via `bind_job_context`; this activity previously never called
    it, so an exception captured here (e.g. `RepartitionBudgetExceededError`) landed in error
    tracking with no way to attribute it to a connector, table, or sync mode."""

    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_activity_binds_source_and_schema_identity_for_captured_exceptions(
        self,
        mock_schema_model: MagicMock,
        mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture_event: MagicMock,
    ) -> None:
        schema = _schema(name="public.charges", s3_folder_name="charges")
        schema.source = MagicMock(source_type="Stripe")
        schema.sync_type = "incremental"
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_job_model.objects.get.return_value.pipeline_version = "v3"
        mock_repartition.return_value = {"outcome": "completed"}

        # Runs in a copied context so the ambient exception properties `bind_job_context` sets
        # don't leak into other tests sharing this interpreter thread.
        ctx = contextvars.copy_context()
        captured_props: dict = {}

        def _run() -> None:
            _maybe_repartition_table(
                RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
                MagicMock(),
            )
            captured_props.update(ambient_exception_properties())

        ctx.run(_run)

        assert captured_props["warehouse_sources_source_type"] == "Stripe"
        assert captured_props["warehouse_sources_schema_name"] == "public.charges"
        assert captured_props["warehouse_sources_sync_type"] == "incremental"
        assert captured_props["warehouse_sources_pipeline_version"] == "v3"
        assert captured_props["warehouse_sources_job_id"] == JOB_ID


NO_ACTIVITY_CONTEXT = object()


class TestRewriteDeadline:
    @parameterized.expand(
        [
            ("outside_an_activity", NO_ACTIVITY_CONTEXT, None),
            ("no_declared_timeout", None, None),
            ("timeout_shorter_than_the_margin", dt.timedelta(minutes=1), None),
            ("timeout_leaves_a_budget", dt.timedelta(hours=6), 22300.0),
        ]
    )
    def test_deadline_is_set_only_when_there_is_budget_to_derive(
        self, _name: str, timeout: object, expected: float | None
    ) -> None:
        info = MagicMock()
        info.start_to_close_timeout = timeout
        info_fn = (
            MagicMock(side_effect=RuntimeError("not in an activity context"))
            if timeout is NO_ACTIVITY_CONTEXT
            else MagicMock(return_value=info)
        )

        with (
            patch(f"{MODULE}.activity.info", info_fn),
            patch(f"{MODULE}.time", MagicMock(monotonic=MagicMock(return_value=1000.0))),
        ):
            assert _rewrite_deadline() == expected


class TestBudgetExhaustion:
    @parameterized.expand([("below_max", 0, False), ("reaching_max", 2, True)])
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_stalled_rewrite_burns_an_attempt_and_gives_up_with_a_cooldown(
        self,
        _name: str,
        prior_attempts: int,
        expect_give_up: bool,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # A rewrite that appended no rows this run (e.g. a resume that spent its whole budget skipping
        # to the checkpoint) is stuck, so budget exhaustion counts as a real failed attempt.
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "attempts": prior_attempts},
            rewrite={"rows_written": 12},
        )
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = RepartitionBudgetExceededError("out of budget", rows_written=0)

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        if expect_give_up:
            schema.clear_repartition_pending.assert_called_once()
            schema.stamp_last_repartition_at.assert_called_once()
            # Charged once, then the marker is cleared rather than re-armed at a higher count.
            assert schema.set_repartition_pending.call_count == 1
            # The rewrite checkpoint must be dropped too, or the next flag cycle would resume the same
            # doomed temp and the give-up would never take effect.
            schema.clear_repartition_rewrite.assert_called_once()
        else:
            assert schema.repartition_pending["attempts"] == prior_attempts + 1
            schema.clear_repartition_pending.assert_not_called()
            schema.stamp_last_repartition_at.assert_not_called()
            schema.clear_repartition_rewrite.assert_not_called()

    @parameterized.expand([("first_attempt", 0), ("last_attempt_before_give_up", 2)])
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_progressing_rewrite_resumes_without_burning_an_attempt(
        self,
        _name: str,
        prior_attempts: int,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # This attempt inherited a checkpoint and appended to it, so a table too large for one budget is
        # converging across runs. It must never give up — even at the last attempt before the cap — and
        # must reset the failure counter. The checkpoint's cumulative temp size sits far below an
        # earlier, longer attempt's high-water mark here, so judging progress by that cumulative size
        # would mislabel a converging rewrite as a stall.
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "attempts": prior_attempts, "rewrite_high_water": 5_000_000},
            rewrite={"rows_written": 230_000},
        )
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = RepartitionBudgetExceededError(
            "out of budget", rows_written=180_000, resumed_from=50_000
        )

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        schema.clear_repartition_pending.assert_not_called()
        schema.clear_repartition_rewrite.assert_not_called()
        schema.stamp_last_repartition_at.assert_not_called()
        updated = schema.set_repartition_pending.call_args.args[0]
        assert updated["attempts"] == 0
        emitted = [c.args[0] for c in mock_capture_event.call_args_list]
        assert "warehouse_repartition_failed" not in emitted
        assert "warehouse_repartition_skipped" in emitted

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_first_over_budget_attempt_that_checkpoints_is_progress_not_a_failure(
        self,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        mock_capture_event: MagicMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        # The first over-budget attempt on a large table inherits no checkpoint, so resumed_from is 0,
        # but it persisted a fresh checkpoint the next run resumes from. That is forward progress, not
        # the treadmill the cap exists to stop: it must not emit a failure event, report to error
        # tracking, or burn an attempt (had_prior_checkpoint distinguishes it from a discarding restart).
        schema = _schema(name="public.usages", s3_folder_name="usages", pending={**PENDING_TARGET, "attempts": 0})
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = RepartitionBudgetExceededError(
            "out of budget", rows_written=162_000_000, resumed_from=0, had_prior_checkpoint=False, checkpoint_saved=True
        )

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        emitted = [c.args[0] for c in mock_capture_event.call_args_list]
        assert "warehouse_repartition_failed" not in emitted
        mock_capture_exception.assert_not_called()
        schema.clear_repartition_pending.assert_not_called()
        schema.stamp_last_repartition_at.assert_not_called()
        assert schema.set_repartition_pending.call_args.args[0]["attempts"] == 0

    @parameterized.expand([("below_max", 0, False), ("reaching_max", 2, True)])
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_restarted_rewrite_burns_an_attempt_however_many_rows_it_wrote(
        self,
        _name: str,
        prior_attempts: int,
        expect_give_up: bool,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # This attempt inherited nothing because the resume path discarded a checkpoint that existed at
        # its start, so it re-streamed from row 0 and covered ground the last attempt already covered. It
        # writes 230M rows doing it, which clears any "did this attempt write anything" test and resets
        # the failure counter. Three schemas looped that way for six weeks, each burning a full budget
        # per run and converging on nothing, because the cap could never count to three.
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "attempts": prior_attempts},
            rewrite={"rows_written": 230_000_000},
        )
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = RepartitionBudgetExceededError(
            "out of budget", rows_written=230_000_000, resumed_from=0, had_prior_checkpoint=True, checkpoint_saved=True
        )

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        if expect_give_up:
            schema.clear_repartition_pending.assert_called_once()
            schema.clear_repartition_rewrite.assert_called_once()
        else:
            assert schema.set_repartition_pending.call_args.args[0]["attempts"] == prior_attempts + 1

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_a_staged_swap_is_resumed_even_after_attempts_are_spent(
        self,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # A worker can die inside the swap after recording the ready marker, leaving temp the source of
        # truth and live possibly already deleted, with the pending marker still carrying the spent
        # count. The attempt cap must not abandon that swap: giving up clears the marker and disarms the
        # missing-live recovery, so the swap is driven to completion (resumed) instead. The rewrite
        # already ran, so this recovery must also not be charged against the cap.
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "attempts": MAX_REPARTITION_ATTEMPTS},
            swap={"state": "ready"},
        )
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.return_value = {"outcome": "completed"}

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        assert mock_repartition.await_count == 1
        schema.clear_repartition_swap.assert_not_called()
        schema.set_repartition_pending.assert_not_called()
        emitted = [c.args[0] for c in mock_capture_event.call_args_list]
        assert "warehouse_repartition_failed" not in emitted

    @parameterized.expand([("live_unreadable",), ("no_delta_table",)])
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_a_skipped_rewrite_does_not_consume_an_attempt(
        self,
        reason: str,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # A rewrite queued on a table whose delta log is unreadable (an OOM-crashed merge) returns a
        # skip every run until the import activity's revive heals it, and the skip leaves the pending
        # marker set for a later run. The attempt is charged up front, so a skip must refund it: three
        # banked skips would otherwise spend the whole cap without a rewrite ever running, and the next
        # run would give up and discard the queued rewrite.
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "attempts": 0},
        )
        # Let charge/refund round-trip through the marker so the net attempt count is observable.
        schema.set_repartition_pending.side_effect = lambda p: setattr(schema, "repartition_pending", p)
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.return_value = {"outcome": "skipped", "reason": reason}

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        assert schema.repartition_pending["attempts"] == 0
        schema.clear_repartition_pending.assert_not_called()


class TestTransientObjectStoreFailure:
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_bare_nosuchkey_stands_down_without_burning_an_attempt(
        self,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        mock_capture_event: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        # A pathless S3 NoSuchKey from an s3fs purge/swap op that raced a concurrent delete is a
        # transient object-store blip, not a repartition bug: it must not emit a failure event or
        # consume one of the table's finite attempts, so the next sync simply retries.
        schema = _schema(name="public.usages", s3_folder_name="usages", pending={**PENDING_TARGET, "attempts": 0})
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = FileNotFoundError("The specified key does not exist.")

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        emitted = [c.args[0] for c in mock_capture_event.call_args_list]
        assert "warehouse_repartition_failed" not in emitted
        # Charged before the rewrite and refunded here, so the net cost is zero.
        assert schema.repartition_pending["attempts"] == 0
        schema.clear_repartition_pending.assert_not_called()

    @parameterized.expand(
        [
            (
                "pgbouncer_login_retry",
                OperationalError(
                    "server login has been failing, cached error: server conn crashed? (server_login_retry)"
                ),
            ),
            ("interface_error", InterfaceError("connection already closed")),
        ]
    )
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_repartition_enabled", return_value=True)
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_db_connection_drop_stands_down_without_reporting_to_error_tracking(
        self,
        _name: str,
        error: Exception,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        _mock_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        mock_capture_event: MagicMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        # A pgbouncer login-retry cooldown or a dropped pooled connection mid-rewrite is infra noise
        # nobody can act on, not a repartition bug — it must not trip a fresh error-tracking issue.
        # The transient metric and the skipped event's reason already carry the visibility.
        schema = _schema(name="public.usages", s3_folder_name="usages", pending={**PENDING_TARGET, "attempts": 0})
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.side_effect = error

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        mock_capture_exception.assert_not_called()
        skip_calls = [c for c in mock_capture_event.call_args_list if c.args[0] == "warehouse_repartition_skipped"]
        assert any(c.args[1].get("reason") == "transient_infra_error" for c in skip_calls)


class TestFeatureFlagGate:
    @parameterized.expand(
        [
            ("flag_off_releases_a_queued_rewrite", False, True, None, "proactive_threshold", False),
            ("flag_off_still_finishes_a_staged_swap", False, True, {"state": "ready"}, "proactive_threshold", True),
            ("flag_off_does_not_block_an_operator", False, True, None, "admin", True),
            ("flag_on_rewrites_as_usual", True, True, None, "proactive_threshold", True),
            ("flag_off_does_not_release_a_nomination", False, False, None, "coarsening_requested", True),
            ("coarsen_flag_off_releases_a_queued_coarsen", True, False, None, "coarsening", False),
            ("repartition_flag_off_keeps_a_queued_coarsen", False, True, None, "coarsening", True),
        ]
    )
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.HeartbeaterSync")
    @patch(f"{MODULE}.repartition_table_in_place", new_callable=AsyncMock)
    @patch(f"{MODULE}.DeltaTableRef")
    @patch(f"{MODULE}.is_auto_coarsen_enabled")
    @patch(f"{MODULE}.is_auto_repartition_enabled")
    @patch(f"{MODULE}.ExternalDataJob")
    @patch(f"{MODULE}.ExternalDataSchema")
    def test_flag_gates_the_queued_rewrite(
        self,
        _name: str,
        enabled: bool,
        coarsen_enabled: bool,
        swap: dict | None,
        trigger_reason: str,
        expect_rewrite: bool,
        mock_schema_model: MagicMock,
        _mock_job_model: MagicMock,
        mock_enabled: MagicMock,
        mock_coarsen_enabled: MagicMock,
        _mock_helper_cls: MagicMock,
        mock_repartition: AsyncMock,
        _mock_heartbeater: MagicMock,
        _mock_capture_event: MagicMock,
    ) -> None:
        mock_enabled.return_value = enabled
        mock_coarsen_enabled.return_value = coarsen_enabled
        schema = _schema(
            name="public.usages",
            s3_folder_name="usages",
            pending={**PENDING_TARGET, "trigger_reason": trigger_reason},
            swap=swap,
        )
        mock_schema_model.objects.select_related.return_value.get.return_value = schema
        mock_repartition.return_value = {"outcome": "completed"}

        _maybe_repartition_table(
            RepartitionActivityInputs(team_id=TEAM_ID, schema_id=SCHEMA_ID, job_id=JOB_ID, source_id=SOURCE_ID),
            MagicMock(),
        )

        assert mock_repartition.await_count == (1 if expect_rewrite else 0)


class TestMaybeFlagPreExtraction:
    @parameterized.expand(
        [
            (
                "generic_s3_error",
                "Generic S3 error: Error getting list response body: HTTP error: "
                "request or response body error: operation timed out",
            ),
            (
                "credential_provider_timeout",
                "Operation not supported: an error occurred while loading credentials: "
                "dispatch failure: timeout: client error (Connect): HTTP connect timeout occurred: timed out",
            ),
        ]
    )
    @patch(f"{MODULE}.capture_exception")
    def test_transient_object_store_error_is_not_reported(
        self, _name: str, message: str, mock_capture: MagicMock
    ) -> None:
        # `get_delta_table` never lets the raw OSError/DeltaError escape for a recognized transient
        # blip — it re-raises `TransientObjectStoreError` instead (see `_capture_unless_transient`).
        # Mocking the raw error here would miss the exact bug this test guards: a caller re-running
        # `is_transient_object_store_error` on the wrapper it actually receives, not on the original.
        schema = _schema(name="stripe_charge", s3_folder_name=None)
        helper = MagicMock()
        helper.get_delta_table = AsyncMock(side_effect=TransientObjectStoreError(message))

        result = _maybe_flag_pre_extraction(schema, MagicMock(), helper, MagicMock(), enabled=True)

        assert result is None
        mock_capture.assert_not_called()

    @parameterized.expand(
        [
            ("operational_error", OperationalError("consuming input failed: server closed the connection")),
            ("interface_error", InterfaceError("connection already closed")),
        ]
    )
    @patch(f"{MODULE}.capture_exception")
    def test_transient_db_connection_drop_is_not_reported(
        self, _name: str, error: Exception, mock_capture: MagicMock
    ) -> None:
        # `get_delta_table` resolves `job.folder_path()` on a pooled app-DB connection (see
        # `DeltaTableRef._get_delta_table_uri`), which can raise these on a stale pooled connection —
        # not the object-store errors `is_transient_object_store_error` alone would catch.
        schema = _schema(name="stripe_charge", s3_folder_name=None)
        helper = MagicMock()
        helper.get_delta_table = AsyncMock(side_effect=error)

        result = _maybe_flag_pre_extraction(schema, MagicMock(), helper, MagicMock(), enabled=True)

        assert result is None
        mock_capture.assert_not_called()

    @patch(f"{MODULE}.capture_exception")
    def test_non_transient_error_is_still_reported(self, mock_capture: MagicMock) -> None:
        schema = _schema(name="stripe_charge", s3_folder_name=None)
        helper = MagicMock()
        error = ValueError("unexpected schema drift")
        helper.get_delta_table = AsyncMock(side_effect=error)

        result = _maybe_flag_pre_extraction(schema, MagicMock(), helper, MagicMock(), enabled=True)

        assert result is None
        mock_capture.assert_called_once_with(error)
