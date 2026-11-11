"""The CDC conformance suite. An engine runs it by subclassing it in a test module of its own."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_FLUSH_MAX_EVENTS
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import CDC_RESET_PENDING_KEY
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    ConformanceEngine,
    ConformanceKit,
    SimulatedCrash,
    SourceDatabase,
    TableDef,
    delete,
    insert,
    truncate,
    update,
)

USERS = TableDef(name="public.users", columns={"id": int, "name": str}, primary_key=("id",))
ORDERS = TableDef(name="public.orders", columns={"id": int, "status": str}, primary_key=("id",))
# In the source's change stream, but not a table the source syncs.
AUDIT = TableDef(name="public.audit", columns={"id": int, "note": str}, primary_key=("id",))

# Above twice the capture flush size, so one transaction spans three buffer files.
_LARGE_TRANSACTION_ROWS = 2 * CDC_FLUSH_MAX_EVENTS + 2_000


class CDCConformanceSuite:
    def make_engine(self, db: SourceDatabase) -> ConformanceEngine:
        raise NotImplementedError

    @pytest.fixture
    def kit(self) -> Iterator[ConformanceKit]:
        db = SourceDatabase([USERS, ORDERS, AUDIT])
        with ConformanceKit(db, self.make_engine(db), captured=[USERS, ORDERS]) as kit:
            yield kit

    def _assert_converged(self, kit: ConformanceKit, table: TableDef) -> None:
        assert kit.live_rows(table) == kit.db.rows(table)
        assert kit.history(table) == kit.db.expected_history(table)

    @pytest.mark.parametrize("read_limit", [None, 4], ids=["one_page", "several_pages"])
    def test_changes_land_in_commit_order(self, kit: ConformanceKit, read_limit: int | None) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"), insert(ORDERS, id=10, status="new"))
        db.commit(update(USERS, {"id": 1}, name="b"), update(USERS, {"id": 1}, name="c"))
        db.commit(insert(AUDIT, id=100, note="ignored"))
        kit.capture(read_limit=read_limit)
        db.commit(update(USERS, {"id": 1}, name="d"), insert(USERS, id=2, name="e"), delete(ORDERS, id=10))
        db.commit(insert(ORDERS, id=11, status="new"))
        db.commit(insert(AUDIT, id=101, note="ignored"))
        kit.capture(read_limit=read_limit)

        for table in (USERS, ORDERS):
            kit.consume(table)
            self._assert_converged(kit, table)
        assert db.confirmed == db.head

    def test_stream_with_no_captured_changes_is_still_released(self, kit: ConformanceKit) -> None:
        kit.db.commit(insert(AUDIT, id=100, note="ignored"))

        kit.capture()

        assert kit.db.confirmed == kit.db.head
        assert kit.buffered_rows(USERS) == []

    @pytest.mark.parametrize("consume_between", [False, True], ids=["unread_files", "consumed_files"])
    def test_capture_crash_before_confirm_replays_exactly_once(
        self, kit: ConformanceKit, consume_between: bool
    ) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"))
        db.commit(update(USERS, {"id": 1}, name="b"), insert(USERS, id=2, name="c"))
        kit.capture()
        kit.consume(USERS)
        db.commit(insert(USERS, id=3, name="e"))
        # The replayed transaction ends the read, so its rows sit at the position the tables hold.
        # It changes one key twice, and only the second version matches the consolidated row.
        db.commit(update(USERS, {"id": 1}, name="d"), update(USERS, {"id": 1}, name="g"), delete(USERS, id=2))

        db.fail_next_confirm()
        with pytest.raises(SimulatedCrash):
            kit.capture()
        if consume_between:
            kit.consume(USERS)
        db.commit(insert(USERS, id=4, name="f"))
        kit.capture()
        kit.consume(USERS)

        self._assert_converged(kit, USERS)

    def test_consumer_crash_between_tables_replays_exactly_once(self, kit: ConformanceKit) -> None:
        db = kit.db
        # Two capture runs write two buffer files, so the first sits wholly below the consolidated
        # table's position once the history table has fallen behind.
        db.commit(insert(USERS, id=1, name="a"), insert(USERS, id=2, name="b"))
        kit.capture()
        db.commit(update(USERS, {"id": 1}, name="c"))
        kit.capture()

        kit.consume(USERS, fail_history_lane=True)
        db.commit(delete(USERS, id=2))
        kit.capture()
        kit.consume(USERS)

        self._assert_converged(kit, USERS)

    def test_key_change_removes_the_old_key(self, kit: ConformanceKit) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"))
        kit.capture()
        kit.consume(USERS)

        db.commit(update(USERS, {"id": 1}, id=9, name="b"))
        kit.capture()
        kit.consume(USERS)

        self._assert_converged(kit, USERS)
        assert kit.deleted_rows(USERS) == {(1,): {"id": 1, "name": "a"}}

    @pytest.mark.parametrize("same_run", [True, False], ids=["same_run_as_insert", "later_run"])
    def test_delete_with_partial_row_keeps_last_values(self, kit: ConformanceKit, same_run: bool) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"), insert(USERS, id=2, name="b"))
        if not same_run:
            kit.capture()
            kit.consume(USERS)

        db.commit(delete(USERS, id=1))
        kit.capture()
        kit.consume(USERS)

        self._assert_converged(kit, USERS)
        assert kit.deleted_rows(USERS) == {(1,): {"id": 1, "name": "a"}}

    def test_truncate_resets_only_the_truncated_table(self, kit: ConformanceKit) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"), insert(ORDERS, id=10, status="new"))
        kit.capture()
        kit.consume(USERS)
        kit.consume(ORDERS)

        db.commit(update(USERS, {"id": 1}, name="b"), update(ORDERS, {"id": 10}, status="paid"))
        db.commit(truncate(USERS))
        db.commit(insert(USERS, id=2, name="c"))
        kit.capture()

        users = kit.schema(USERS)
        assert users.cdc_mode == "snapshot"
        assert users.sync_type_config["reset_pipeline"] is True
        assert kit.schema(ORDERS).cdc_mode == "streaming"
        # The snapshot reads the table after this run, so no change from before it may be replayed.
        assert kit.buffered_rows(USERS) == []
        # The stream is past the truncate, so a later run does not reset the table again.
        assert db.confirmed == db.head

        db.commit(insert(USERS, id=3, name="d"))
        kit.capture()
        kit.snapshot(USERS)
        kit.consume(USERS)
        kit.consume(ORDERS)

        assert kit.live_rows(USERS) == db.rows(USERS)
        self._assert_converged(kit, ORDERS)

    @pytest.mark.parametrize("crash", [False, True], ids=["clean_run", "crash_inside_transaction"])
    def test_large_transaction_lands_exactly_once(self, kit: ConformanceKit, crash: bool) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"))
        db.commit(*(insert(USERS, id=i, name=f"n{i}") for i in range(2, 2 + _LARGE_TRANSACTION_ROWS)))

        if crash:
            kit.store.fail_write(3)
            with pytest.raises(SimulatedCrash):
                kit.capture()
            # Two files of the open transaction are flushed, and the stream must still hold all of it.
            assert db.confirmed == 1
            kit.consume(USERS)
        kit.capture()
        kit.consume(USERS)

        self._assert_converged(kit, USERS)

    def test_lost_stream_is_recreated_and_tables_resnapshot(self, kit: ConformanceKit) -> None:
        db = kit.db
        db.commit(insert(USERS, id=1, name="a"))
        kit.capture()
        kit.consume(USERS)

        db.lose_stream()
        db.commit(update(USERS, {"id": 1}, name="b"))
        kit.capture()

        users = kit.schema(USERS)
        assert db.stream_recreations == 1
        assert users.cdc_mode == "snapshot"
        assert users.sync_type_config["reset_pipeline"] is True
        assert CDC_RESET_PENDING_KEY not in users.sync_type_config
        assert kit.buffered_rows(USERS) == []

        db.commit(insert(USERS, id=2, name="c"))
        kit.capture()
        kit.snapshot(USERS)
        kit.consume(USERS)

        assert kit.live_rows(USERS) == db.rows(USERS)
