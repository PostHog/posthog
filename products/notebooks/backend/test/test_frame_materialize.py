import uuid

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from temporalio import exceptions

from posthog.schema import QueryStatus

from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.temporal.common.clickhouse import ClickHouseMemoryLimitExceededError

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

    def test_resource_budget_error_is_terminal_with_a_clear_message(self):
        # A deterministic ClickHouse resource-budget failure (rejected up front) must be
        # non-retryable and carry a user-facing message — not retried to the schedule bound
        # and finalized with the generic 'try re-running' fallback.
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

        with (
            patch.object(frame_materialize, "_print_clickhouse_sql", return_value=("SELECT 1", {})),
            patch.object(frame_materialize, "_materialize_slots"),
            patch.object(
                frame_materialize.ClickHouseClient,
                "post_query",
                side_effect=ClickHouseMemoryLimitExceededError("MEMORY_LIMIT_EXCEEDED", query="SELECT 1"),
            ),
        ):
            with self.assertRaises(exceptions.ApplicationError) as caught:
                frame_materialize.materialize_frame(inputs)

        self.assertTrue(caught.exception.non_retryable)
        status = manager.get_query_status()
        self.assertTrue(status.complete and status.error)
        self.assertIn("materialization limits", status.error_message or "")
