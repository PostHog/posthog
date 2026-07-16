import io
import uuid
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from temporalio import exceptions

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.errors import InternalCHQueryError
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.common.clickhouse import ClickHouseMemoryLimitExceededError, ClickHouseTooManyRowsOrBytesError

from products.notebooks.backend import frame_store
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.temporal import frame_materialize

_DISPATCH_TARGET = "products.notebooks.backend.temporal.client.start_frame_materialize_workflow"


def _registered_inputs(
    team_id: int, notebook_short_id: str, user_id: int, query: str = "select 1"
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
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
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
                patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
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
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
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
        )
        key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)
        self.addCleanup(object_storage.delete, key)

        with self.settings(NOTEBOOKS_FRAME_STORE_CH_WRITES=True, OBJECT_STORAGE_ENABLED=True):
            returned_key = frame_materialize.materialize_frame(inputs)

        self.assertEqual(returned_key, key)
        status = manager.get_query_status()
        self.assertTrue(status.complete and not status.error)
        self.assertEqual(status.results, {"object_key": key})

        import pyarrow as pa  # noqa: PLC0415 — keeps the heavy dep off the module import path

        data = object_storage.read_bytes(key)
        assert data is not None
        table = pa.ipc.open_stream(data).read_all()
        self.assertEqual(table.num_rows, 3)
        self.assertTrue(pa.types.is_string(table.schema.field("u").type))
        self.assertEqual(table.column("u").to_pylist(), [frame_uuid] * 3)

    def test_insert_sql_escapes_credentials_and_splices_nothing_else(self):
        # The s3() literals are the only spliced zone; quote-doubling alone mishandles a
        # trailing backslash (it escapes the closing quote), so a regression here turns a
        # config value into SQL-syntax breakage — or worse.
        with self.settings(
            OBJECT_STORAGE_ENDPOINT="http://store:19000",
            OBJECT_STORAGE_BUCKET="bucket",
            OBJECT_STORAGE_ACCESS_KEY_ID="ke'y\\",
            OBJECT_STORAGE_SECRET_ACCESS_KEY="s'ec\\ret",
        ):
            sql = frame_materialize._insert_into_s3_sql("SELECT 1", "notebooks/frames/team_1/nb/abc.arrow")
        self.assertEqual(
            sql,
            "INSERT INTO FUNCTION s3("
            "'http://store:19000/bucket/notebooks/frames/team_1/nb/abc.arrow', "
            "'ke''y\\\\', 's''ec\\\\ret', 'ArrowStream')\n"
            "SELECT 1",
        )

    @parameterized.expand(
        [
            # In-band budget failure: deterministic, must be terminal with the actionable
            # message — not retried to the schedule bound.
            ("memory_budget", 241, True, "materialization limits"),
            # Unrecognized code (e.g. an S3-side blip): plausibly transient, retry per policy.
            ("unrecognized_code", 499, False, None),
        ]
    )
    def test_insert_error_code_maps_to_terminal_or_retryable(self, _name, code, terminal, expected_message):
        inputs, manager = _registered_inputs(self.team.id, self.notebook.short_id, self.user.id)
        error = InternalCHQueryError("DB::Exception", code=code)

        with (
            self.settings(NOTEBOOKS_FRAME_STORE_CH_WRITES=True),
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(frame_materialize, "sync_execute", side_effect=error),
        ):
            with self.assertRaises(exceptions.ApplicationError if terminal else InternalCHQueryError) as caught:
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
        inputs, manager = _registered_inputs(self.team.id, self.notebook.short_id, self.user.id)
        key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)

        with (
            self.settings(NOTEBOOKS_FRAME_STORE_CH_WRITES=True),
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
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
