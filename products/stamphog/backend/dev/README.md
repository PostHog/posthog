# stamphog dev harness

A full-chain, single-process testbed for the stamphog product: a signed GitHub webhook driven
all the way through review, merged-PR capture, and the daily Slack digest — runnable on a laptop.

This is **dev-only** code. It is not imported by production, not part of the test suite, and not
wired into any route or task. It exists to exercise the real chain end to end with GitHub and
Slack faked at their natural seams.

## Run it

From the repo root, with the dev stack up (`./bin/start` — Postgres + Redis):

```bash
flox activate -- bash -c 'DEBUG=1 ./manage.py shell < products/stamphog/backend/dev/harness.py'
```

The harness prints a readable trace and asserts at each step. Exit code 0 means every step passed.

If the stamphog product DB is missing (`relation "stamphog_..." does not exist`), create + migrate
the product databases once:

```bash
flox activate -- bash -c 'DEBUG=1 ./manage.py migrate_product_databases'
```

### Env knobs

- `HARNESS_TEAM_ID=<id>` — reuse an existing dev team instead of creating a `stamphog-harness` org
- `SANDBOX_MODE=stub|real` — `stub` (default) injects a scripted APPROVED engine verdict; `real`
  runs the production docker sandbox (needs a real repo + installation, so the fakes don't cover it)
- `KEEP=1` — leave the harness rows in place instead of deleting them at the end

## What runs, and what's faked

Real: the webhook view (with real HMAC verification), the Celery task (eager), the review
activities (fetch context / run in sandbox / post verdict), the digest tasks, the ORM, and all the
audience / channel-resolution / digest logic.

Faked, each at one seam:

| Fake           | Seam (exact import patched)                                                                                                        |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| GitHub         | `products.stamphog.backend.logic.github_client.github_request` (+ the two limiter helpers)                                         |
| Temporal       | `products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow` → inline workflow that calls the real activities in order |
| Sandbox (stub) | `products.stamphog.backend.temporal.activities.get_sandbox_class_for_backend` → fake sandbox returning scripted engine output      |
| Slack          | `products.stamphog.backend.logic.slack_digest.SlackIntegration` and `...channel_resolution.SlackIntegration`                       |
| Digest LLM     | `products.stamphog.backend.logic.digest.get_llm_client` → raises, so the deterministic fallback summary is used                    |

The GitHub fake serves the **real** `.stamphog/policy.yml` + `.stamphog/review-guidance.md` from
this checkout (read via pathlib) for the default-branch policy fetch, and records every write
(approve reviews, issue comments) in `recorder.github_writes`. The Slack fake records every
`chat_postMessage` and serves a scripted workspace channel list. A real `Integration` row
(`kind="slack"`) is created so the DB id-lookup path is exercised even though the client is faked.

## The scenario

1. Create a `stamphog-harness` org/team + a Slack `Integration`, then a `StamphogRepoConfig`
   (`digest_enabled=True`).
2. Signed `pull_request` `opened` (#101) → PR + `ReviewRun` created → inline workflow (stub) →
   run COMPLETED/approved, APPROVE review recorded on GitHub.
3. `synchronize` (#101) → a queued run is superseded by the next push, which is reviewed for real.
4. `closed`+`merged` (#101) → merge facts recorded, `audience_key` stamped (`team-devex` via the
   scripted GraphQL teams response).
5. `send_daily_digests()` → `DigestChannel` auto-provisioned (`slack_name_match`, enabled),
   `DigestRun` completed, the Block Kit message printed.
6. A merged PR by an author with no team and no declared channel → stays undigested
   (`repo:` audience, no provisioning without a declared channel).
7. `cleanup()` deletes the harness rows (skipped with `KEEP=1`).

## Why the DB plumbing looks the way it does

stamphog models live on a **separate product database**. Three real quirks have to be reconciled
to run this outside the pytest product-DB harness:

1. The task's `transaction.atomic()` targets the _default_ DB, but the product-DB
   `select_for_update` (supersede path) needs an ambient transaction on the _stamphog_ connection.
2. Product reads route to the reader connection outside tests, so an in-flight write is invisible
   to a later read on a different connection.
3. Eager Celery closes DB connections after each task; a transaction left open across a task is
   rolled back on close, losing the rows.

The harness reconciles all three the way the pytest suite does: it routes product reads to the
writer (`posthog.product_db_router.TEST`), replaces the task module's `transaction` with a shim
whose `atomic()` targets the stamphog writer (so each task commits its own rows before Celery's
cleanup) and whose `on_commit` runs **inline**, and drives the activities in-thread via the plain
sync body under `@asyncify` (`activity.__wrapped__`) so they share the one connection.

Note on `transaction.on_commit`: the harness DB writes are in autocommit, so in principle
`on_commit` fires at commit — but under the shim's ambient product-DB transaction it would fire
only at the outer commit, after the read that needs the row. Running it inline (as the pytest
suite does) is what keeps the inline workflow firing while the rows are visible.

## Gotchas

- `_resolve_repo_config` is oldest-wins **across teams** by `(installation_id, repository)`. A
  leftover `harness/` config from a crashed run would hijack this run's webhooks onto a dead team,
  so the harness purges any pre-existing `harness/` rows at startup.
- Cleanup's org delete fires Team cache-clear signals that hit Redis. With the dev stack down it is
  skipped with a warning (the stamphog rows are still cleaned); run with the stack up for a full
  teardown.
