# Error tracking internal import map (phase 0)

Generated during facade isolation kickoff.
This tracks cross-product imports that currently bypass the facade.

## Current public-ish surfaces consumed externally

| Internal module                                                 | External consumers                                                                                                                                                                             | Capability class                       |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `backend.models`                                                | `posthog/models/remote_config.py`, `posthog/models/product_intent/product_intent.py`, `posthog/management/commands/*`, plus tests/admin/demo                                                   | read/list/detail, counters, async/task |
| `backend.hogql_queries.*`                                       | `posthog/hogql_queries/query_runner.py`, `products/signals/backend/temporal/backfill_error_tracking.py`, `products/posthog_ai/scripts/hogql_example/__init__.py`                               | read/list analytics query execution    |
| `backend.api` package                                           | `posthog/api/__init__.py`                                                                                                                                                                      | HTTP routing entrypoint                |
| `backend.api.issues` serializer                                 | `backend/hogql_queries/error_tracking_query_runner_v1.py`, `backend/hogql_queries/error_tracking_issue_correlation_query_runner.py`                                                            | read/list serialization coupling       |
| `backend.remote_config` and `backend.api.suppression_rules`     | `posthog/models/remote_config.py`                                                                                                                                                              | config read                            |
| `backend.embedding`, `backend.indexed_embedding`, `backend.sql` | `posthog/clickhouse/schema.py`, `posthog/clickhouse/migrations/*`, `posthog/api/embedding_worker.py`, `products/signals/backend/management/commands/cleanup_signals.py`, `posthog/conftest.py` | schema/constants (infra)               |
| `backend.tools.search_issues`                                   | `ee/hogai/core/agent_modes/presets/error_tracking.py`                                                                                                                                          | tool invocation                        |

## Initial migration focus (stack order)

1. **Read-only issue access** (lowest risk): move model reads to `backend/facade/api.py` (`list_issues`, `get_issue`, `issue_exists`, fingerprint lookup, values lookup).
2. **Cross-product issue readers**: migrate `ee/hogai/context/error_tracking/context.py`, `products/tasks/backend/repository_readiness.py`, `posthog/tasks/usage_report.py`. ✅ completed in PR 2.
3. **Task and digest callers**: migrate `posthog/tasks/email.py` and `backend/weekly_digest.py` consumers. ✅ completed in PR 3.
4. **Presentation migration**: move `backend/api/*.py` viewsets into `backend/presentation/views.py`/`serializers.py` and route through facade.
5. **Boundary enforcement + cleanup**: add `backend/facade/contracts.py`, `backend:contract-check`, and `tach` interface block once legacy paths are removed.

## Graphite stack template

```bash
# Base branch

gt checkout master

gt create -m "chore(error-tracking): add facade kickoff and import map"
# PR 1

gt create -m "refactor(error-tracking): migrate issue readers to facade"
# PR 2

gt create -m "refactor(error-tracking): migrate digest and task callers"
# PR 3

gt create -m "refactor(error-tracking): move api viewsets to presentation layer"
# PR 4

gt create -m "chore(error-tracking): enforce facade interfaces and contracts"
# PR 5
```

Use `gt modify -a` to amend each branch and `gt submit --stack` to open/update the full stacked PR chain.
