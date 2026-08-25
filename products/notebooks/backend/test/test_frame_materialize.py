import io
import uuid
from types import SimpleNamespace

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings

from parameterized import parameterized
from temporalio import activity, exceptions
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute import _KILL_SWITCH_SETTINGS, KillSwitchLevel
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded, ClickHouseQuerySizeExceeded, ClickHouseQueryTimeOut
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.common.clickhouse import ClickHouseMemoryLimitExceededError, ClickHouseTooManyRowsOrBytesError

from products.notebooks.backend import frame_store
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.temporal import frame_materialize

_DISPATCH_TARGET = "products.notebooks.backend.temporal.client.start_frame_materialize_workflow"


def _printed_sql(sql: str = "SELECT 1") -> frame_materialize._PrintedFrameSQL:
    return frame_materialize._PrintedFrameSQL(
        sql=sql, values={}, passes=1, print_seconds=0.0, describe_seconds=0.0, resolve_seconds=0.0
    )


def _per_query_memory_error() -> ClickHouseQueryMemoryLimitExceeded:
    # wrap_clickhouse_query_error sets this out of band, and it defaults to False — the
    # cluster-pressure reading. Only the query's own budget overrun is terminal.
    error = ClickHouseQueryMemoryLimitExceeded()
    error.is_per_query_limit = True
    return error


def _registered_inputs(
    team_id: int, notebook_short_id: str, user_id: int, query: str = "select 1", ch_writes: bool = False
) -> tuple["frame_materialize.FrameMaterializeInputs", QueryStatusManager]:
    query_id = uuid.uuid4().hex
    inputs = frame_materialize.FrameMaterializeInputs(
        query_id=query_id,
        team_id=team_id,
        notebook_short_id=notebook_short_id,
        user_id=user_id,
        query=query,
        query_hash="abc123",
        cache_key=f"notebook-frame:{team_id}:abc123",
        ch_writes=ch_writes,
    )
    manager = QueryStatusManager(query_id, team_id)
    manager.store_query_status(QueryStatus(id=query_id, team_id=team_id))
    manager.register_cache_key_mapping(inputs.cache_key)
    return inputs, manager


class TestFrameMaterializeEnqueue(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbfm001")

    def _enqueue(self, *, user_id, query, **kwargs):
        return frame_materialize.enqueue_frame_materialization(
            team=self.team,
            user_id=user_id,
            notebook_short_id=self.notebook.short_id,
            query=query,
            **kwargs,
        )

    def test_different_users_do_not_share_a_materialize_job(self):
        # The printed SQL applies the enqueuing user's access controls, so two
        # differently-permissioned users in one team must get separate jobs (and separate
        # object keys) — otherwise a restricted user joins a privileged user's in-flight job
        # and downloads rows their own access controls would deny.
        query = "select number from numbers(1) -- different_users"
        with patch.object(frame_materialize, "materialize_frame"):  # leave jobs "running"
            first = self._enqueue(user_id=101, query=query, _test_only_inline=True)
            same_user_again = self._enqueue(user_id=101, query=query, _test_only_inline=True)
            other_user = self._enqueue(user_id=202, query=query, _test_only_inline=True)
        self.assertEqual(first.id, same_user_again.id)  # same user + query → dedup join
        self.assertNotEqual(first.id, other_user.id)  # different user → separate job

    def test_failed_dispatch_lets_the_retry_enqueue_a_fresh_job(self):
        # A Temporal dispatch failure must roll back the status + dedup mapping. Otherwise a
        # re-run dedups onto a job that will never run and polls a dead query_id until the
        # 20-minute TTL. The retry proves rollback happened: it must actually execute rather
        # than short-circuit on a stale dedup hit.
        query = "select number from numbers(1) -- failed_dispatch"
        with patch(_DISPATCH_TARGET, side_effect=Exception("temporal unreachable")):
            with self.assertRaises(Exception):
                self._enqueue(user_id=self.user.id, query=query)
        with patch.object(frame_materialize, "materialize_frame") as run:
            self._enqueue(user_id=self.user.id, query=query, _test_only_inline=True)
        run.assert_called_once()

    def _registered_inputs(self) -> tuple["frame_materialize.FrameMaterializeInputs", QueryStatusManager]:
        return _registered_inputs(self.team.id, self.notebook.short_id, self.user.id)

    @parameterized.expand(
        [
            # Scan/memory budget: MEMORY_LIMIT_EXCEEDED rejected up front.
            (
                "memory_budget",
                ClickHouseMemoryLimitExceededError("MEMORY_LIMIT_EXCEEDED", query="SELECT 1"),
                "materialization limits",
            ),
            # Output budget: max_result_bytes trips (a huge result from a tiny scan must not
            # persist a multi-GB object nor be retried).
            (
                "result_size_budget",
                ClickHouseTooManyRowsOrBytesError("TOO_MANY_ROWS_OR_BYTES", query="SELECT 1"),
                "too large",
            ),
        ]
    )
    def test_budget_error_is_terminal_with_a_clear_message(self, _name, clickhouse_error, expected_message):
        # A deterministic ClickHouse budget failure must be non-retryable and carry a
        # user-facing message — not retried to the schedule bound and finalized with the
        # generic 'try re-running' fallback.
        inputs, manager = self._registered_inputs()

        with (
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=_printed_sql()),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(frame_materialize.ClickHouseClient, "post_query", side_effect=clickhouse_error),
        ):
            with self.assertRaises(exceptions.ApplicationError) as caught:
                frame_materialize.materialize_frame(inputs)

        self.assertTrue(caught.exception.non_retryable)
        status = manager.get_query_status()
        self.assertTrue(status.complete and status.error)
        self.assertIn(expected_message, status.error_message or "")

    def test_mid_stream_failure_removes_the_corrupt_object_and_surfaces_the_real_error(self):
        # ClickHouse streams 200 before execution finishes; a mid-stream failure can close
        # the body cleanly with exception text appended instead of tearing the read. Without
        # the Arrow EOS-marker check that corrupt object would be stored, the status
        # finalized as succeeded, and the poll would 302 the kernel to garbage.
        inputs, manager = self._registered_inputs()
        body_without_eos = b"\xff\xff\xff\xff" + b"x" * 4096 + b"Code: 241. DB::Exception: Memory limit exceeded"

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            with (
                patch.object(frame_materialize, "_print_clickhouse_sql", return_value=_printed_sql()),
                patch.object(frame_materialize, "_materialize_slots"),
                patch.object(frame_materialize.ClickHouseClient, "post_query") as post_query,
                patch.object(
                    frame_materialize,
                    "_fetch_query_log_exception",
                    return_value=(241, "Memory limit (for query) exceeded"),
                ),
            ):
                post_query.return_value.__enter__.return_value = SimpleNamespace(raw=io.BytesIO(body_without_eos))
                with self.assertRaises(exceptions.ApplicationError) as caught:
                    frame_materialize.materialize_frame(inputs)

            self.assertTrue(caught.exception.non_retryable)
            status = manager.get_query_status()
            self.assertTrue(status.complete and status.error)
            self.assertIn("materialization limits", status.error_message or "")
            # The corrupt bytes were written to the deterministic key and must not survive.
            self.assertIsNone(object_storage.list_objects(frame_store.team_prefix(self.team.id)))

    @parameterized.expand(
        [
            # A storage-side upload failure (or a torn stream) with no ClickHouse-side
            # exception: only a confirmed query-side exception may be terminal, else a
            # transient S3 blip becomes a hard cell failure.
            ("no_query_log_entry", None),
            # Our own read-timeout abandonment cancels the query server-side
            # (cancel_http_readonly_queries_on_client_close), which the query log records as
            # QUERY_WAS_CANCELLED — that must not be classified as a doomed query.
            ("query_was_cancelled", (394, "Query was cancelled")),
        ]
    )
    def test_stream_failure_stays_retryable(self, _name, query_log_result):
        inputs, manager = self._registered_inputs()

        with (
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=_printed_sql()),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(frame_materialize.ClickHouseClient, "post_query") as post_query,
            patch.object(frame_materialize.frame_store, "write_stream", side_effect=ObjectStorageError("torn")),
            patch.object(frame_materialize, "_fetch_query_log_exception", return_value=query_log_result) as lookup,
        ):
            post_query.return_value.__enter__.return_value = SimpleNamespace(raw=io.BytesIO(b""))
            with self.assertRaises(ObjectStorageError):
                frame_materialize.materialize_frame(inputs)

        lookup.assert_called_once()
        status = manager.get_query_status()
        self.assertFalse(status.complete)  # not finalized — Temporal retries per policy


class TestFrameMaterializeCHWrites(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.notebook = Notebook.objects.create(team=self.team, short_id="nbfmch1")

    def test_ch_writes_materializes_a_readable_arrow_object(self):
        # End-to-end through the real path: pooled DESCRIBE, the stringify second pass,
        # the INSERT assembly around real printed HogQL (trailing SETTINGS clause,
        # %(hogql_val)s placeholders), and CH writing the object itself. Catches any
        # assembly change that produces invalid SQL, and the loss of
        # output_format_arrow_string_as_string / the UUID stringification, which would
        # hand pandas raw bytes.
        frame_uuid = "018e0e7a-1111-2222-3333-444444444444"
        inputs, manager = _registered_inputs(
            self.team.id,
            self.notebook.short_id,
            self.user.id,
            query=f"select number as n, toUUID('{frame_uuid}') as u from numbers(3)",
            ch_writes=True,
        )
        key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)
        self.addCleanup(object_storage.delete, key)

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            returned_key = frame_materialize.materialize_frame(inputs)

        self.assertEqual(returned_key, key)
        status = manager.get_query_status()
        self.assertTrue(status.complete and not status.error)
        # The bucket is recorded next to the key so the status survives a bucket change:
        # the poll signs against what the writer used, not whatever the setting says later.
        self.assertEqual(status.results, {"object_key": key, "bucket": settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET})

        import pyarrow as pa  # noqa: PLC0415 — keeps the heavy dep off the module import path

        data = object_storage.read_bytes(key)
        assert data is not None
        table = pa.ipc.open_stream(data).read_all()
        self.assertEqual(table.num_rows, 3)
        self.assertTrue(pa.types.is_string(table.schema.field("u").type))
        self.assertEqual(table.column("u").to_pylist(), [frame_uuid] * 3)

    def test_ch_writes_zero_row_result_writes_a_valid_empty_object(self):
        # Empty results are common in notebooks (a filter matching nothing). CH must still
        # write a valid (header-only) Arrow object for a zero-row INSERT INTO s3, or stat_frame
        # would see no object → retry → generic failure. Guards against a CH version/setting
        # change (or a switch away from ArrowStream) that stops emitting the empty object.
        inputs, manager = _registered_inputs(
            self.team.id,
            self.notebook.short_id,
            self.user.id,
            query="select number as n from numbers(0)",
            ch_writes=True,
        )
        key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)
        self.addCleanup(object_storage.delete, key)

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            frame_materialize.materialize_frame(inputs)

        status = manager.get_query_status()
        self.assertTrue(status.complete and not status.error)

        import pyarrow as pa  # noqa: PLC0415 — keeps the heavy dep off the module import path

        data = object_storage.read_bytes(key)
        assert data is not None
        self.assertEqual(pa.ipc.open_stream(data).read_all().num_rows, 0)

    def test_insert_sql_binds_s3_args_as_parameters(self):
        # The s3() endpoint/bucket/key/credentials are bound as query params, not spliced as
        # literals: sync_execute's single %-substitution pass escapes them (so a % or quote in
        # a config value can't corrupt the format pass or reach the credential zone). A
        # regression back to literal splicing is the design doc's named injection risk.
        # Path-style URL uses the CH-reachable endpoint, NOT OBJECT_STORAGE_ENDPOINT.
        with self.settings(
            NOTEBOOKS_FRAME_STORE_S3_ENDPOINT="http://store:19000",
            NOTEBOOKS_FRAME_STORE_S3_BUCKET="bucket",
            OBJECT_STORAGE_ACCESS_KEY_ID="ke'y%s",
            OBJECT_STORAGE_SECRET_ACCESS_KEY="s'ec\\ret",
        ):
            sql, params = frame_materialize._insert_into_s3_sql("SELECT 1", "notebooks/frames/team_1/nb/abc.arrow")
        self.assertEqual(
            sql,
            "INSERT INTO FUNCTION s3(%(_nb_s3_url)s, %(_nb_s3_key)s, %(_nb_s3_secret)s, 'ArrowStream')\nSELECT 1",
        )
        # Raw values, unescaped, under reserved keys — escaping happens in the substitution
        # pass, and nothing hostile is ever concatenated into the statement text.
        self.assertEqual(params["_nb_s3_url"], "http://store:19000/bucket/notebooks/frames/team_1/nb/abc.arrow")
        self.assertEqual(params["_nb_s3_key"], "ke'y%s")
        self.assertEqual(params["_nb_s3_secret"], "s'ec\\ret")

    def test_insert_sql_prod_endpoint_is_virtual_hosted_and_keyless(self):
        # The prod branch that dev/CI never exercises: an empty CH endpoint (cluster reaches AWS
        # via IAM role) must yield a virtual-hosted HTTPS URL and NO inline credentials — not a
        # scheme-less `/bucket/key` from concatenating an empty endpoint (which CH rejects).
        # The region is OBJECT_STORAGE_REGION on purpose: the app presigns the read with that
        # same region, and a frames-only region would sign the URL under a scope AWS rejects.
        with self.settings(
            NOTEBOOKS_FRAME_STORE_S3_ENDPOINT="",
            NOTEBOOKS_FRAME_STORE_S3_BUCKET="ph-frames",
            OBJECT_STORAGE_REGION="eu-west-1",
            OBJECT_STORAGE_ACCESS_KEY_ID="should-be-ignored",
            OBJECT_STORAGE_SECRET_ACCESS_KEY="should-be-ignored",
        ):
            sql, params = frame_materialize._insert_into_s3_sql("SELECT 1", "notebooks/frames/team_1/nb/abc.arrow")
        self.assertEqual(sql, "INSERT INTO FUNCTION s3(%(_nb_s3_url)s, 'ArrowStream')\nSELECT 1")
        self.assertEqual(
            params["_nb_s3_url"],
            "https://ph-frames.s3.eu-west-1.amazonaws.com/notebooks/frames/team_1/nb/abc.arrow",
        )
        self.assertNotIn("_nb_s3_key", params)

    @parameterized.expand(
        [
            # Budget failures sync_execute rewraps as APIException subclasses (NOT
            # InternalCHQueryError) — the case the earlier hand-built InternalCHQueryError
            # masked. Must be terminal, else the canonical whale failures re-scan on every retry.
            ("memory_wrapped", _per_query_memory_error(), True, "materialization limits"),
            # "(total)" / "(for user)" memory pressure: the cluster was busy, not this query too
            # big, so the same query can succeed on retry. Finalizing it would both waste the
            # retry budget and tell the user to narrow a query that is fine.
            ("cluster_memory_pressure", ClickHouseQueryMemoryLimitExceeded(), False, None),
            ("timeout_wrapped", ClickHouseQueryTimeOut(), True, "time limit"),
            # A big-but-valid query (printer-expanded IN lists) that overflows max_query_size:
            # deterministic, terminal with an actionable message, not a retry.
            ("query_size_wrapped", ClickHouseQuerySizeExceeded(), True, "too large to materialize"),
            # A user-safe CH query error surfaced at execution (e.g. type mismatch): terminal
            # with the real, sanitized message — not retried into a generic failure.
            (
                "exposed_user_error",
                ExposedCHQueryError("Code: 53. DB::Exception: There is no supertype for types", code=53),
                True,
                "no supertype for types",
            ),
            # The scan-budget overrun. wrap_clickhouse_query_error maps 307 to
            # CHQueryErrorTooManyBytes, which is an ExposedCHQueryError, so it lands in the
            # sanitized-message branch rather than the code-table one. It must still read as
            # the budget message: the same overrun says the same thing on either transport.
            (
                "too_many_bytes",
                ExposedCHQueryError("Code: 307. DB::Exception: Limit for bytes to read exceeded", code=307),
                True,
                "materialization limits",
            ),
            # Unrecognized code (e.g. an S3-side blip): plausibly transient, retry per policy.
            ("unrecognized_code", InternalCHQueryError("DB::Exception", code=499), False, None),
        ]
    )
    def test_insert_error_maps_to_terminal_or_retryable(self, _name, error, terminal, expected_message):
        inputs, manager = _registered_inputs(self.team.id, self.notebook.short_id, self.user.id, ch_writes=True)

        with (
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=_printed_sql()),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(frame_materialize, "sync_execute", side_effect=error),
        ):
            with self.assertRaises(exceptions.ApplicationError if terminal else type(error)) as caught:
                frame_materialize.materialize_frame(inputs)

        status = manager.get_query_status()
        if terminal:
            self.assertTrue(caught.exception.non_retryable)
            self.assertTrue(status.complete and status.error)
            self.assertIn(expected_message, status.error_message or "")
        else:
            self.assertFalse(status.complete)  # not finalized — Temporal retries per policy

    def test_oversize_object_is_deleted_and_terminal(self):
        # max_result_bytes bounds results returned to a client, not an INSERT's sink — the
        # post-write size check is the only output cap on this path. Removing it as
        # "redundant" would let a huge-per-row query persist an unbounded object.
        inputs, manager = _registered_inputs(self.team.id, self.notebook.short_id, self.user.id, ch_writes=True)
        key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)

        with (
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=_printed_sql()),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(frame_materialize, "sync_execute", return_value=None),
            patch.object(
                frame_materialize.frame_store, "stat_frame", return_value=frame_materialize._MAX_RESULT_BYTES + 1
            ),
            patch.object(frame_materialize.frame_store, "delete_frame") as delete_frame,
        ):
            with self.assertRaises(exceptions.ApplicationError) as caught:
                frame_materialize.materialize_frame(inputs)

        delete_frame.assert_called_once_with(key)
        self.assertTrue(caught.exception.non_retryable)
        status = manager.get_query_status()
        self.assertTrue(status.complete and status.error)
        self.assertIn("too large", status.error_message or "")


@pytest.mark.asyncio
async def test_exhausted_retries_stop_at_three_scans_and_finalize_the_status():
    # A transient tear leaves the activity retryable, so nothing in the activity itself ends
    # the job. Two things have to hold at the workflow level: the scan repeats a bounded
    # number of times (each attempt re-runs the whole ClickHouse query), and the run still
    # reaches a terminal state. Without the second one the kernel polls a never-completing
    # status until its own deadline and reports a timeout instead of the real error.
    attempts = 0
    marked_failed = False

    @activity.defn(name="notebook-frame-materialize")
    async def tear_every_attempt(inputs: frame_materialize.FrameMaterializeInputs) -> str:
        nonlocal attempts
        attempts += 1
        raise ObjectStorageError("stream torn mid-upload")

    @activity.defn(name="notebook-frame-materialize-mark-failed")
    async def mark_failed(inputs: frame_materialize.FrameMaterializeInputs) -> None:
        nonlocal marked_failed
        marked_failed = True

    inputs = frame_materialize.FrameMaterializeInputs(
        query_id="fm-retry-cap",
        team_id=1,
        notebook_short_id="nbfm001",
        user_id=1,
        query="select 1",
        query_hash="abc123",
        cache_key="notebook-frame:1:abc123",
    )
    task_queue = str(uuid.uuid4())

    # Time skipping fast-forwards the retry backoff, so the policy's real intervals cost the
    # suite nothing.
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[frame_materialize.NotebookFrameMaterializeWorkflow],
            activities=[tear_every_attempt, mark_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    frame_materialize.NotebookFrameMaterializeWorkflow.run,
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    assert attempts == 3
    assert marked_failed


class TestFrameMaterializeKillSwitchCaps(APIBaseTest):
    @parameterized.expand(
        [
            ("off", {}),
            ("light", dict(_KILL_SWITCH_SETTINGS[KillSwitchLevel.LIGHT])),
            ("full", dict(_KILL_SWITCH_SETTINGS[KillSwitchLevel.FULL])),
        ]
    )
    def test_printed_sql_carries_kill_switch_ceilings(self, _name: str, overrides: dict[str, int]):
        with patch.object(frame_materialize, "kill_switch_overrides", return_value=overrides):
            sql = frame_materialize._generate_sql(self.team, self.user, "select 1", output_format=None).sql

        memory_ceiling = overrides.get("max_memory_usage")
        if memory_ceiling is None:
            assert "max_memory_usage" not in sql
        else:
            assert f"max_memory_usage={memory_ceiling}" in sql
        # The lane's own caps already sit under every ceiling, so the merge must keep them
        # rather than widen them to the kill switch's looser numbers.
        assert f"max_threads={frame_materialize._MAX_THREADS}" in sql
        assert f"max_bytes_to_read={frame_materialize._MAX_BYTES_TO_READ}" in sql


class TestFrameMaterializePrintPasses(APIBaseTest):
    @parameterized.expand(
        [
            ("arrow_safe_column", "select 1 as n", [("n", "UInt8")], 1),
            ("arrow_binary_column", "select 1 as uuid", [("uuid", "UUID")], 2),
        ]
    )
    def test_pass_count_tracks_whether_a_column_needs_stringifying(
        self, _name: str, query: str, described: list[tuple[str, str]], expected_passes: int
    ):
        # The second pass re-prints the whole query through a wrapper and is the dominant
        # cost of a materialization, so the reported count has to reflect what actually ran.
        printed = frame_materialize._print_clickhouse_sql(
            lambda _sql, _values: described, self.team, self.user, query, output_format=None
        )

        assert printed.passes == expected_passes
        assert ("toString" in printed.sql) is (expected_passes == 2)

    def test_resolve_time_is_actually_recorded(self):
        # The reported split reads leaf keys out of HogQLQueryExecutor's own timings, so a
        # renamed or relocated span downgrades the field to a silent zero rather than an
        # error — which is exactly how the first version of this shipped, reporting
        # `create_hogql_database` that the executor never records on this path.
        printed = frame_materialize._print_clickhouse_sql(
            lambda _sql, _values: [("n", "UInt8")], self.team, self.user, "select 1 as n", output_format=None
        )

        assert printed.resolve_seconds > 0
