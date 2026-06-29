#### Searching for existing entities

"find / which / do we have / what's our X chart" questions about PostHog-created entities are SQL searches against `system.*` (`system.insights`, `system.dashboards`, `system.cohorts`, `system.feature_flags`, `system.experiments`, `system.surveys`, `system.notebooks`), **not** `*-list` walks.

Required order on every run, no shortcuts:

1. `info execute-sql` AND `info read-data-warehouse-schema` — load both tool guides, even if a skill is already loaded.
2. `read-data-warehouse-schema` — confirms the table's columns. Schema markdown in skills/references (`models-*.md`, `querying-posthog-data` docs) is documentation, **not** a substitute — call the tool.
3. `execute-sql` against `system.*` — uses only columns confirmed in step 2.
4. `<entity>-get` (e.g. `insight-get`, `dashboard-get`) — verifies the entity shape; do NOT re-`execute-sql` by ID.

<bad-example>
User: rename / find / list … (any `system.*` question)
Assistant: [Calls `execute-sql` against `system.insights` without first running `read-data-warehouse-schema` — OR runs `read-data-warehouse-schema` partway through, only after several `execute-sql` calls thrashed]
WRONG — the rule is "schema first, every run, no shortcuts." Even if early SQL happens to work (or the search is thrashing on `WHERE name ILIKE …` variants), you've already failed: every successful `execute-sql` against `system.*` MUST be preceded by `read-data-warehouse-schema` in the same run. Same for `info read-data-warehouse-schema` before the first `read-data-warehouse-schema` call. Skipping or postponing either step is a hard violation.
</bad-example>
