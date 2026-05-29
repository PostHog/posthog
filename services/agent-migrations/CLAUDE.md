# agent-migrations — Single source of truth for the v2 agent platform schema

Plain SQL migrations + a tiny [node-pg-migrate](https://github.com/salsita/node-pg-migrate)
runner on top. Owns every table the v2 services (ingress, runner, janitor,
tests) read from or write to.

## Rules of engagement

1. **Append-only.** Every change is a new migration file. No editing,
   renaming, or deleting committed migrations — production has already
   applied them. Mistakes are corrected with a follow-up migration.

2. **One concern per file.** Adding a column for X and a table for Y are
   two migrations. A reverted change is easier to reason about when each
   file does one thing.

3. **Idempotent SQL only.** Every `CREATE` uses `IF NOT EXISTS`; every
   `ALTER TABLE ADD COLUMN` uses `IF NOT EXISTS`. Same migration can run
   safely against a fresh DB (e.g. test reset) and against prod (where
   most prior migrations have already run).

4. **No down migrations.** Forward-only. Reverting in prod means a
   follow-up forward migration. The down section is left as a single
   comment so node-pg-migrate doesn't bark.

5. **The harness uses `reset()`.** Tests pull `reset()` from this package
   rather than re-implementing schema setup. That keeps the test DB and
   prod schema rooted in the same SQL.

## File naming

`migrations/<unix-millis>_<snake_name>.sql`. The timestamp prefix is what
node-pg-migrate orders by; pick `Date.now()` at authoring time.

## Running

- Prod: `bin/migrate --scope=agent_runtime` →
  `pnpm --filter @posthog/agent-migrations migrate`.
- Local: `AGENT_DB_URL=… pnpm --filter @posthog/agent-migrations migrate`.
- Tests: `import { reset } from '@posthog/agent-migrations'` — drops
  everything in `public` and reapplies every migration in order.

## What goes here vs Django

The Django `agent_stack` app owns the _authoring_ tables
(`agent_application`, `agent_revision`) in production via its own
migrations. The migrations in this package recreate those tables in the
test harness only — production never runs them against the main posthog
DB.

The split lets the test harness boot a single DB without standing up
Django, while production keeps authoring tables in the main product DB
under Django's migration history.
