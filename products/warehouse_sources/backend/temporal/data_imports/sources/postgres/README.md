# Postgres source

Sync types available per table: `full_refresh`, `incremental`, `append`, `cdc`, and `xmin`.

## xmin replication

xmin is a **cursorless incremental** sync type. It tracks changes using Postgres's hidden
`xmin` system column — the transaction id (XID) that last inserted or updated each row — so a
table can sync incrementally even when it has no good user-defined cursor (e.g. no
`updated_at`).

Each sync captures a ceiling (`pg_snapshot_xmin(pg_current_snapshot())`, the lowest
still-running xid) on the row-serving connection, reads every row whose `xmin` falls in
`[previous ceiling, this ceiling)`, and persists the ceiling at job completion. Rows are
upserted by primary key, so a re-read of an already-synced row is idempotent.

The first sync has no previous ceiling, so it reads the **whole table** with no `xmin`
predicate. It still captures the ceiling first and persists it afterwards, which means rows
committed while the scan runs are re-read on the next sync instead of being skipped. A
multi-wrap epoch jump falls back to the same whole-table read.

### When to use it

- The table has **no reliable incremental cursor** and you'd otherwise use `full_refresh`.
- The database is **not under heavy write churn** (every sync is a full sequential scan — see
  limitations).
- You don't need deletes captured (if you do, choose `cdc`).

### Limitations

These are inherent to how `xmin` works, not bugs:

- **No hard deletes.** A vacuumed deleted tuple leaves nothing for `xmin` to observe, so deletes
  never propagate. Updates and inserts are captured; deletes are not.
- **Full sequential scan every sync.** `xmin` has no index (`xmin::text::bigint` is an
  expression), so each sync scans the whole table. On large tables this can hit the
  10-minute `statement_timeout`. The unindexed-field warning fires in the UI.
- **Frozen tuples are invisible to future diffs.** Since PG 9.4 freezing sets
  `HEAP_XMIN_FROZEN` in the tuple's infomask and leaves the raw `xmin` alone (it no longer
  rewrites it to `FrozenTransactionId`, 2), so a frozen row keeps an xid that says nothing about
  when it last changed. The initial whole-table read is what guarantees those rows were synced,
  because a frozen row can't be re-detected afterwards.
- **PostgreSQL 13+ only.** The durable cursor uses the 64-bit, wraparound-safe `xid8`
  (`pg_snapshot_xmin`), available from PG13.
- **Heap tables and materialized views only.** Plain views and foreign tables have no physical
  `xmin`; partitioned parents are excluded (a single global ceiling can't span independent
  per-partition xid spaces).
- **Requires a primary key** for clean upsert deduplication.

### Wraparound

The bare 32-bit `xmin` counter wraps every ~4 billion transactions, and a tuple's `xmin`
carries no epoch, so a raw comparison is only meaningful relative to the epoch the stored cursor
was captured in. We persist the full `xid8` ceiling and its epoch (`xmin_num_wraparound`) so
wraparound is handled explicitly: a single wrap reads `>= lower OR < upper`; a multi-wrap re-reads
the whole table, as does a backfill.

Bounding a backfill by `xmin < ceiling` is wrong on a cluster that has wrapped: the ceiling's low
32 bits are a small remainder of the current epoch, and every tuple written in an earlier epoch
sits above it, so the read silently returns almost nothing. Use
`reset_wrapped_xmin_cursors` (management command) to find schemas whose cursor was captured past a
wraparound and clear it, which makes the next sync re-read the whole table. A cursor captured past
a wraparound is a candidate rather than proof: the command reports how much of the xid space each
backfill window covered, and a window that covered most of the space may have read the whole table
anyway.

### Feature flag

Gated behind `dwh-postgres-xmin` (organization-scoped). See
`products/data_warehouse/backend/logic/data_load/service.py:is_xmin_enabled_for_team`.
