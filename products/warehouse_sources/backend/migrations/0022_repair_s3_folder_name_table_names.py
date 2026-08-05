"""Rename DataWarehouseTables mis-named by feeding the snake_cased `s3_folder_name` into the table
name. `build_table_name` only lower-cases (`BalanceTransaction` -> `stripe_balancetransaction`),
but the buggy code lower-cased the *snake_cased* folder (`balance_transaction` ->
`stripe_balance_transaction`), breaking HogQL queries on the conventional name. The Delta data is
untouched (the S3 folder was always the snake_cased name) — this is a pure rename.

The match is deliberately exact: a table whose name IS what the bug produced
(`build_table_name(s3_folder_name)`) and that differs from the correct `build_table_name(name)`.
That excludes tables named by other code paths (direct-query / DuckLake tables are stored as the
raw schema name, not via build_table_name) and excludes multi-schema migration pins (dotted names,
where building from the folder is correct). A row that would collide with another live table of the
target name is left untouched.

The SQL mirrors `build_table_name`: lower(coalesce(prefix,'') || source_type || '_' || name).
Run the matching SELECT first (see the PR description) to preview the rows it will touch.
"""

from django.db import migrations

REPAIR_SQL = """
-- migration-analyzer: safe reason=Renames ~20 specific rows matched by an exact-name predicate (verified by a dry-run SELECT); brief lock, no batching needed.
UPDATE posthog_datawarehousetable AS t
SET name = lower(coalesce(src.prefix, '') || src.source_type || '_' || replace(s.name, '.', '__')),
    updated_at = now()
FROM posthog_externaldataschema AS s
JOIN posthog_externaldatasource AS src ON src.id = s.source_id
WHERE s.table_id = t.id
  AND s.deleted = false
  AND t.deleted = false
  AND strpos(s.name, '.') = 0   -- exclude multi-schema migration pins (dotted names)
  AND s.s3_folder_name IS NOT NULL
  -- the table name IS exactly the buggy output (built from the snake_cased folder)...
  AND t.name = lower(coalesce(src.prefix, '') || src.source_type || '_' || replace(s.s3_folder_name, '.', '__'))
  -- ...and that differs from the correct name (built from the raw schema name)...
  AND lower(coalesce(src.prefix, '') || src.source_type || '_' || replace(s.s3_folder_name, '.', '__'))
      <> lower(coalesce(src.prefix, '') || src.source_type || '_' || replace(s.name, '.', '__'))
  -- ...and nothing live already holds the target name for this source (avoid an ambiguous table).
  AND NOT EXISTS (
      SELECT 1
      FROM posthog_datawarehousetable AS t2
      WHERE t2.deleted = false
        AND t2.id <> t.id
        AND t2.team_id = t.team_id
        AND t2.external_data_source_id = t.external_data_source_id
        AND t2.name = lower(coalesce(src.prefix, '') || src.source_type || '_' || replace(s.name, '.', '__'))
  );
"""


class Migration(migrations.Migration):
    dependencies = [
        ("warehouse_sources", "0021_backfill_externaldataschema_s3_folder_name_gap"),
    ]

    operations = [
        # Irreversible: there is no meaningful way to re-apply the bug, and the rename restores the
        # conventional name the data was always queryable under.
        migrations.RunSQL(sql=REPAIR_SQL, reverse_sql=migrations.RunSQL.noop, elidable=True),
    ]
