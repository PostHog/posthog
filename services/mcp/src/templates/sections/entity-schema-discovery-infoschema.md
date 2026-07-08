#### Searching for existing entities

"find / which / do we have / what's our X chart" questions about PostHog-created entities are SQL searches against `system.*` (`system.insights`, `system.dashboards`, `system.cohorts`, `system.feature_flags`, `system.experiments`, `system.surveys`, `system.notebooks`), **not** `*-list` walks.

Required order on every run, no shortcuts — schema first, every run:

1. Confirm the table's columns with an `execute-sql` against `system.information_schema.columns`, e.g. `SELECT column_name, data_type, description FROM system.information_schema.columns WHERE table_name = 'system.insights'`. Schema markdown in skills/references (`models-*.md`, `querying-posthog-data` docs) is documentation, **not** a substitute — query the schema.
2. `execute-sql` against `system.*` — uses only columns confirmed in step 1.
3. `<entity>-get` (e.g. `insight-get`, `dashboard-get`) — verifies the entity shape; do NOT re-`execute-sql` by ID.

<bad-example>
User: rename / find / list … (any `system.*` question)
Assistant: [Calls `execute-sql` against `system.insights` without first confirming its columns via `system.information_schema.columns` — OR checks the schema partway through, only after several `execute-sql` calls thrashed]
WRONG — the rule is "schema first, every run, no shortcuts." Even if early SQL happens to work (or the search is thrashing on `WHERE name ILIKE …` variants), you've already failed: every successful `execute-sql` against a `system.*` entity table MUST be preceded by an `execute-sql` against `system.information_schema.columns` for that table in the same run. Skipping or postponing the schema check is a hard violation.
</bad-example>
