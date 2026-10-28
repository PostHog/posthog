# Warehouse sources agent guide

Read the `implementing-warehouse-sources` skill (`.agents/skills/implementing-warehouse-sources/SKILL.md`) before you build or extend a source here.

## Source tests

Every test under `<source>/tests/` must catch a runtime failure that no other test catches.
Source tests were about a fifth of the monorepo's test cases until [#113325](https://github.com/PostHog/posthog/pull/113325) cut the ones that caught nothing.
Read [the testing reference](../../../../../../.agents/skills/implementing-warehouse-sources/references/testing.md) when you add or change a source test: it lists the cut patterns and what to write instead.

- A source test never reads back a declaration: `lists_tables_without_credentials`, `connection_host_fields`, `api_docs_url`, versions, `get_source_config` fields, endpoint names, primary keys or page sizes. The shared invariants in `tests/` cover the ones that matter.
- A source test never re-tests shared code: `get_non_retryable_errors()` key membership, `get_schemas(names=...)` filtering, `get_documented_tables()`, a forwarding `source_for_pipeline`, or the `rest_source` paginators, auth and retries.
- A source test never patches `make_tracked_session`, mocks `ResumableSourceManager`, or patches a private name in `common/`. `posthog/test/repo_invariants/test_warehouse_source_test_shapes.py` fails a new test file that does. Use `SourceDriver` or `scripted_network` from `common/testing`.
- A new case reaches a branch or line that no other case reaches. Parameterize statuses and modes that share a code path.
