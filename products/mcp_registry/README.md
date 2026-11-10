# MCP registry (retired)

A ranked, searchable index of MCP servers: every server in the official MCP registry, joined with usage data from MCP Analytics for the servers our customers measure.
The idea: any registry can list MCP servers, but only PostHog can rank them by what agents actually did with them.
An agent connects to one MCP server, asks it for the servers a task needs, and gets back a ranked list with instructions for connecting to each.

It ran internal-only behind the `mcp-registry` feature flag from September 2026 (#85710, #95309, #98789, #99314) until it was removed in November 2026, because nobody was working on it while it kept costing time.
For example, self-hosted installs ran the crawl and probe, which got their outbound traffic flagged (#130094).

**Production notes** (usage, reliability, latency, ranking quality, with the queries to refresh them) are in an internal PostHog notebook: https://us.posthog.com/project/2/notebooks/YLuJGOJz.
Read it before you bring the product back.

## What is left here

Only the Django app shell: `models.py`, the migrations, and `apps.py`.
Squash migrations in other apps depend on `mcp_registry.0001_squash_*`, so the app stays in `INSTALLED_APPS`.
The `mcp_registry_*` tables and their data remain.
None of them has a foreign key to a team, user, or organization table, so a later migration can drop them with `SafeDropTable` without blocking anything.

## How to bring it back

1. `git revert` the removal PR (`git log --grep "remove the MCP registry product"`).
   That restores the crawl, aggregate, probe and rank pipeline, the API (`discover`, `compare`, `retrieve`, `measured_projects`), the `mcp-registry-discover` and `mcp-registry-server-get` MCP tools, the `/mcp-registry` scene, the daily schedule, and the measured-server helpers in `products/mcp_analytics/backend/facade/api.py`.
   It also brings back the earlier README, which explains each pipeline stage, ranking versions, and connection instructions.
2. Rerun codegen (`hogli build:openapi`, MCP tool schema snapshots), since generated files will have moved on since the removal.
3. If the tables were dropped in the meantime, the revert brings back the models, so `makemigrations` recreates them, and `python manage.py sync_mcp_registry` rebuilds the index.
4. Fix the issues below before you turn the schedule back on.

## What worked

- Separate pipeline stages (crawl, aggregate, probe, rank), so one failing stage doesn't stop the others.
- Ranking versions kept side by side (`v1_metadata_prior` vs `v2_measured_trust`) and compared with `/compare/`. Every score keeps its components, so a ranking can always be explained.
- Cautious linking of measured traffic to registry rows: an unclear match gets its own row instead of being merged into the wrong one.
- Connection instructions that mark each step for the agent to run or for a person to do, including Stripe Projects provisioning.
- Tool descriptions that tell agents to treat whatever a server says about itself as data, not instructions.
- Agents found the discover tool from its description alone and kept calling it every week, with no announcement or docs.

## What to fix before it comes back

1. Keep it cloud-only. The revert restores the `is_cloud()` gate from #132164; also unschedule it on self-hosted installs (#131531).
2. Only expose the MCP tools to callers the feature flag lets through. The tools were advertised to everyone while the endpoint was flag-gated, so calls from outside PostHog failed.
3. The daily sync often didn't finish and nothing alerted anyone.
   Split the stages into separate tasks that can resume, alert when a run doesn't finish, and retry the crawl when outbound requests fail.
4. Probe coverage was far too low to tell servers apart: most of the index was never probed, so most results tied on score.
   Probe many more servers a day, hosted endpoints first, and skip hosts on blocklists.
5. `discover` got slower as the index grew, up to timeouts.
   Precompute search (embeddings or Postgres full-text search) so it doesn't scan the whole table.
6. Aggregation ran one ClickHouse query per project at a busy hour, and some of them were rejected for capacity.
   Batch them, or run them at a quieter time.
7. Agents often called `discover` without `intent`.
   Make the parameter harder to miss, or fall back to a useful default.
8. Still open from the original plan: owner opt-in before showing measured stats publicly (`measured_public`), outcome feedback that resists gaming, and a UI (likely the mcp_store marketplace).
