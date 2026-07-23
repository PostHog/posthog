import io
import uuid
from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from temporalio import exceptions

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.common.clickhouse import ClickHouseMemoryLimitExceededError, ClickHouseTooManyRowsOrBytesError

from products.notebooks.backend import frame_store
from products.notebooks.backend.models import Notebook
from products.notebooks.backend.temporal import frame_materialize

_DISPATCH_TARGET = "products.notebooks.backend.temporal.client.start_frame_materialize_workflow"


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
        query_id = uuid.uuid4().hex
        inputs = frame_materialize.FrameMaterializeInputs(
            query_id=query_id,
            team_id=self.team.id,
            notebook_short_id=self.notebook.short_id,
            user_id=self.user.id,
            query="select 1",
            query_hash="abc123",
            cache_key=f"notebook-frame:{self.team.id}:abc123",
        )
        manager = QueryStatusManager(query_id, self.team.id)
        manager.store_query_status(QueryStatus(id=query_id, team_id=self.team.id))
        manager.register_cache_key_mapping(inputs.cache_key)
        return inputs, manager

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
