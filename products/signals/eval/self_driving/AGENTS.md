# Self-driving SWE eval

End-to-end benchmark of the autonomous signals→PR loop against the **real** local stack.
Read `DESIGN.md` (what/why, stages, scorers) and `TASK_SPEC.md` (task authoring) first.

## Layout

| Path                   | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `DESIGN.md`            | Benchmark design: stages, scorers, difficulty tiers                         |
| `TASK_SPEC.md`         | Task authoring convention (`task.json`, `signals.json`, `repo/`, `verify/`) |
| `tasks/<task_id>/`     | Task universes: planted defect + signals + hidden behavioral tests          |
| `harness/provision.py` | Per-task team, synthetic GitHub integration + repo cache entries            |
| `harness/seed.py`      | ClickHouse telemetry seeding (direct `sharded_events` inserts)              |
| `harness/runner.py`    | Drives one task through the real pipeline; collects report/patch/logs       |
| `harness/grade.py`     | Behavioral test execution + LLM judges (no Braintrust dependency)           |
| `harness/drive.py`     | Full-run driver: parallelism, timeouts, result JSON, Braintrust hand-off    |
| `eval_selfdriving.py`  | Braintrust logging (project `signals-self-driving`)                         |

## Running

```bash
# 1. Print the mount map for the current task set and start the worker with it
DEBUG=1 python manage.py shell -c "
from products.signals.eval.self_driving.harness.drive import print_mount_map
print_mount_map()"
SANDBOX_REPO_MOUNT_MAP=<that value> DEBUG=1 python manage.py start_temporal_worker

# 2. Prereqs: Django on :8000, MCP dev server on :8787 (cd services/mcp && pnpm dev),
#    ClickHouse + Temporal + personhog (PERSONHOG_ADDR=localhost:50052), docker.

# 3. Drive the run (in another shell)
DEBUG=1 python manage.py shell -c "
from products.signals.eval.self_driving.harness.drive import drive
drive(trials=1, parallelism=2)"
```

## Environment gotchas (hard-won)

- `.env` must have `CLICKHOUSE_DATABASE=posthog` and `PERSONHOG_ADDR=localhost:50052` —
  without the latter, `fetch_signal_type_examples_activity` drops every signal.
- Repo-selection candidates come from `IntegrationRepositoryCacheEntry` rows (heavy cache),
  not `Integration.repository_cache` JSON; provision writes both, with fresh `updated_at`
  so the TTL gate short-circuits the GitHub sync for the synthetic installation.
- The synthetic integration token never expires (`expires_in` ~10y in config), so
  `get_github_token()` serves it from cache; combined with `SANDBOX_REPO_MOUNT_MAP`
  (clone becomes a bind mount) no call ever reaches GitHub.
- Zendesk fixture records require `url, type, tags (JSON string), created_at, priority, status`
  on top of `id, subject, description` — pydantic rejects otherwise.
- The sandbox derives its MCP URL as `http://host.docker.internal:8787/mcp` when
  `SITE_URL` is localhost — the wrangler MCP dev server must be running.
