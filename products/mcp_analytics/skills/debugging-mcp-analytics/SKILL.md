---
name: debugging-mcp-analytics
description: >
  Debug, support, and build PostHog MCP Analytics — product analytics for MCP
  servers (the `@posthog/mcp` and `posthog.mcp` SDKs plus the mcp_analytics
  product). Use when MCP analytics data looks wrong or missing ("events aren't
  showing", "intent clusters are empty", "sessions are missing", "per-tool
  numbers look wrong"), when writing queries over `$mcp_*` events by hand, or
  when doing feature work on the SDKs, the dashboard and its query runners, the
  self-instrumented MCP server, the `wizard mcp-analytics` install command, or
  the in-app onboarding. Covers the repo map, the `$mcp_*` vocabulary and where
  each property comes from, the rules that silently corrupt metrics when
  ignored, the end-to-end pipeline and where each stage breaks, and which repo
  to change. For reading the data rather than fixing it, prefer the
  `exploring-mcp-*` and `improving-mcp-tools` skills.
---

# Debugging MCP analytics

**Product analytics for MCP servers.** A team ships an MCP server; the `@posthog/mcp` SDK
wraps it in one line; every tool call, agent **intent**, and failure lands in PostHog as a
`$mcp_*` event you can query, chart, alert on, and cluster — plus a dedicated dashboard. The
MCP-layer sibling of `@posthog/ai`.

The differentiator is **intent**: not "ran `query_run` 14 times" but "was trying to find a
churn cohort". Explicit non-goal: this does **not** replace LLM analytics / AI observability
— generation traces, prompt/response, and token cost belong there.

Status: **beta**, TypeScript and Python SDKs shipped, whole product still behind the
`mcp-analytics` early-access flag (`products/mcp_analytics/frontend/featurePreviewGate.ts`).
PostHog dogfoods it — its own MCP server instruments itself, and that data drives the
dashboard. Public tracking: mega-issue **PostHog/posthog#64016**, which is the live source
for roadmap and customer wishlist.

## Repos

GitHub is the source of truth for where the code lives. Paths below are in-repo; for the
repos outside this monorepo, resolve a local checkout via
[references/local-repos.md](references/local-repos.md) rather than assuming a location.

| Concern                           | Repo                          | Where to look                                                                                                                                                                                                                                                                                 |
| --------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Product / dashboard**           | `PostHog/posthog` (this repo) | `products/mcp_analytics/` — Django/DRF + HogQL query runners + Temporal, Kea frontend, the `query-mcp-*` tool registry, and the analysis skills                                                                                                                                               |
| **Self-instrumented server**      | `PostHog/posthog` (this repo) | `services/mcp/` — PostHog's own MCP server (Hono); the dogfood event producer. Also hosts the _generated_ `query-mcp-*` handlers                                                                                                                                                              |
| **Shared query reference**        | `PostHog/posthog` (this repo) | [`models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md) — `products/posthog_ai/skills/querying-posthog-data/references/`                                                                                                                                 |
| **TypeScript SDK** `@posthog/mcp` | `PostHog/posthog-js`          | `packages/mcp/` — the library customers install. Vocabulary source of truth: `src/extensions/constants.ts`. `docs/ARCHITECTURE.md` now covers conversation anchoring (ADR-0004) but trails the newest era handling — where it and `CHANGELOG.md` disagree, trust the changelog and the source |
| **Python SDK** `posthog.mcp`      | `PostHog/posthog-python`      | `posthog/mcp/` — mirrors `posthog.ai`. Ships inside `posthog` (`pip install posthog`); `mcp`/`fastmcp` are lazily-imported peer deps, **no `[mcp]` extra**. At TS parity since 7.40.0-7.42.1 — MCP Python SDK v2, conversation anchoring, typed errors, client UA/vendor                      |
| **Docs**                          | `PostHog/posthog.com`         | `contents/docs/mcp-analytics/` (incl. `surfaces/`), plus `src/hooks/productData/mcp_analytics.tsx` and the `mcp_analytics` entry in `src/data/tools.ts`                                                                                                                                       |
| **Install codemod**               | `PostHog/context-mill`        | `context/skills/mcp-analytics/{config.yaml,description.md}`                                                                                                                                                                                                                                   |
| **Wizard CLI**                    | `PostHog/wizard`              | `bin.ts`, `src/commands/mcp-analytics.ts`, `src/lib/programs/mcp-analytics/`                                                                                                                                                                                                                  |
| **Wizard test harness**           | `PostHog/wizard-workbench`    | `apps/mcp-analytics/` fixtures                                                                                                                                                                                                                                                                |

**Don't conflate:**

- `PostHog/mcp-analytics` is the **archived prototype** of this SDK — stuck at `0.0.9` with an
  old `track(server, {...})` API. It published under the same `@posthog/mcp` name, so grepping
  that name can land you there. npm `@posthog/mcp` now resolves to `PostHog/posthog-js`.
- `products/mcp_store/` is the MCP server marketplace / team gateway, not this product. (Older
  notes also mention a `products/mcp/` build-tooling directory; it no longer exists — the server
  and its generation tooling live in `services/mcp/`.)
- `wizard mcp add` installs the PostHog **MCP server** into a coding agent. That is NOT
  `wizard mcp-analytics`, which instruments the user's _own_ server.

> Line numbers drift and this area moves fast — **grep for the symbol**, never trust a
> remembered line number. Confirm a checkout is on a sane branch before quoting its code.

## Hard rules (break these and the numbers are silently wrong)

These are the failure modes that produce a plausible-looking answer rather than an error.

1. **Always resolve the effective tool name through `EFFECTIVE_TOOL_SQL`.** The expression
   lives once, in `products/mcp_analytics/backend/hogql_queries/base.py`:
   `coalesce(nullIf(toString(properties.$mcp_exec_tool_call_name), ''), toString(properties.$mcp_tool_name))`.
   It exists because a single-exec server can report the tool two different ways, and the two
   eras of data coexist. Today `services/mcp` resolves the inner tool itself and passes it
   straight in as the tool name (`execToolName()` in `src/hono/tool-executor.ts`, which falls
   back to the literal `exec` when the inner command isn't recognized), so
   `$mcp_tool_name` usually already holds the real tool. `$mcp_exec_tool_call_name` is
   registered in `posthog/taxonomy/taxonomy.py` and coalesced defensively here, but **nothing
   on master emits it** — treat it as historical rows plus in-flight work, not current
   producer behaviour. Either way, aggregate through the coalesce: hand-rolling
   `properties.$mcp_tool_name` alone silently buckets unrecognized exec calls under `exec`,
   and misses any data that does carry the dedicated property.
2. **Failures come from `$mcp_is_error` / `$mcp_error_type` / `$mcp_error_status`, never
   `$exception`.** `$exception` can be disabled, isn't emitted when no error value is passed,
   and never matched new-SDK events — so querying it returns nothing rather than failing.
3. **Dash the in-progress bucket.** Every time-bucketed chart zero-fills and marks the final
   incomplete interval via `products/mcp_analytics/frontend/timeBuckets.ts` (`resolveWindow`,
   `normalizeBucket`, `buildBucketKeys`, `lastBucketIsInProgress`). Omit it and a partial
   period reads as a real decline.
4. **`harness` is derived, and its logic exists in three places that must move in lockstep:**
   `products/mcp_analytics/backend/mcp_harness.py` (source of truth — see its module
   docstring), `products/mcp_analytics/frontend/dashboard/harnessRegistry.ts`, and
   [`models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md).
5. **Check which SDK version the dogfood server is on before trusting dogfood data.**
   `services/mcp` consumes the SDK through an alias in its `package.json` and has historically
   lagged the published version, so version-dependent properties (typed error types, `$lib`
   identity, payload redaction) can be absent from PostHog's own data even when documented as
   current. A query filtering on `$lib = 'posthog-node-mcp'` silently excludes all dogfood
   traffic if that pin predates SDK 0.7.0. Note too that `services/mcp` uses the
   **custom-dispatcher** (`PostHogMCP`) path rather than `instrument()`, so behaviour living
   only in the `instrument()` path — stable sessions, `$identify` deduplication, `_meta`-based
   client identity — has never applied to it at any version.
6. **Know which session model produced the data.** Under the stateless spec there is no
   transport session, so `$session_id` is only stable if the server opted into conversation
   anchoring — `enableConversationId`, which is **off by default**. With it off, a stateless
   client's sessions fragment (often one per request); with it on, `$session_id` is derived
   from an agent-echoed handle and survives reconnects, restarts, and pods. Check the flag
   before diagnosing "fragmented sessions" as an ingestion problem. See
   [references/stateless-and-sessions.md](references/stateless-and-sessions.md).
7. **There are no SQL template files.** Every dashboard and tool-quality query is a typed
   query runner behind the generic `/query/` endpoint. A `backend/templates/*.sql` referenced
   by older notes no longer exists.

## Event vocabulary

All data lives on the shared ClickHouse **`events`** table — there is **no dedicated table**.
Every metric is an aggregation over `$mcp_tool_call`, usually grouped by `$session_id`.

Source of truth for the SDK-emitted names is `packages/mcp/src/extensions/constants.ts` in
`PostHog/posthog-js`, exported as `PostHogMCPAnalyticsEvent` / `PostHogMCPAnalyticsProperty`
(import them for typesafe queries). PostHog-side descriptions — including the server-stamped
and exec-mode properties the SDK does not define — live in `posthog/taxonomy/taxonomy.py`.

**Events** (all `$`-prefixed; non-`$` names would be treated as customer events):
`$mcp_tool_call` (primary), `$mcp_tools_list`, `$mcp_initialize`, `$mcp_missing_capability`,
`$mcp_resource_read` / `$mcp_resources_list`, `$mcp_prompt_get` / `$mcp_prompts_list`,
`$identify`, `$exception`.

> **`$mcp_initialize` is not a reliable session anchor — but check whose server you're looking
> at.** The 2026-07-28 revision removes the `initialize` handshake, so a customer server on the
> SDK's `instrument()` path emits nothing for a stateless client. **PostHog's own server is the
> exception**: `services/mcp` fires the same `$mcp_initialize` event from `server/discover` as
> from `initialize` (`dispatcher.ts::recordDiscoveryRequest` covers both entry points), so the
> event is present in dogfood data either way. Treat its absence as meaningful only for
> customer servers. The real anchor is now the conversation handle when the server enables it —
> [references/stateless-and-sessions.md](references/stateless-and-sessions.md) covers the
> resolution order and the delivery protocol. Live consequence, for customer servers only:
> `frontend/mcpAnalyticsOnboardingLogic.ts` derives `has_initialize` from this event, so a
> stateless customer server reads as `not-instrumented` until its first tool call. Onboarding
> still completes — `hasToolCall` is checked first, in both that selector and
> `statusFromProbeDefinitions`. Projects on `services/mcp` are unaffected, since it emits the
> event from `server/discover`.

Full property tables — split by provenance (SDK-emitted vs stamped by PostHog's own server vs
exec-mode only), the identifier distinctions, per-version SDK behaviour, and TypeScript/Python
parity — are in [references/event-vocabulary.md](references/event-vocabulary.md). Read that
before writing queries or changing what gets captured.

## Reading the data

**Prefer the dedicated analysis skills** over hand-written HogQL; they already encode the
exec-mode and harness handling that Hard rules 1 and 4 describe:

- `exploring-mcp-tool-usage` — front door / router: takes a broad "how is my MCP doing"
  question and dispatches to the right typed tool or focused skill. Start here.
- `exploring-mcp-tool-quality` — error rates, latency, reach, failing and slow tools.
- `exploring-mcp-sessions` — session list, per-session tool calls, intent.
- `exploring-mcp-intent-clusters` — "what are people trying to do" clusters.
- `improving-mcp-tools` — eval-scored campaign loop: measure, make one bounded fix, re-measure.

**Typed tools** exist for most questions and are preferable to raw SQL: `posthog:query-mcp-tool-stats`,
`-daily-stats`, `-failures`, `-failure-occurrences`, `-descriptions`, `-neighbors`,
`-sample-intents`, `-top-users`, and `posthog:query-mcp-harness-breakdown`, plus session tools
(`posthog:mcp-analytics-sessions-list` / `-tool-calls` / `-generate-intent`) and the intent-cluster
tools. They are declared in `products/mcp_analytics/mcp/tools.yaml`.

**Harness** is the friendly label for the calling client (Claude Code, Cursor, ChatGPT,
Windsurf, and ~30 other buckets). It is resolved at query time only, with no stored column:
`mcp_harness.py::HARNESS_TOKEN_SQL` picks the strongest available signal in priority order
(`mcp_vendor_client` -> Claude Code user-agent surface -> Grok user-agent -> `$mcp_client_name`
-> `mcp_session_client_name` -> generic user-agent token -> `$mcp_oauth_client_name`), then
`harness_label_sql()` buckets it (or `harness_label_or_token_sql()`, which names an
unrecognized client verbatim instead of collapsing it into "Other" — use it for ranked
top-N lists, never where labels feed an array or unbounded GROUP BY).

**`$mcp_client_name` is one mid-priority input, not a synonym for harness** — grouping by
it directly gives a different, messier answer. It rides on the session's `initialize` and
is absent from the tool calls that follow, so on its own it leaves most traffic
unattributed; `mcp_session_client_name` is the session-pinned fallback the token chain
reaches for next.

For hand-written SQL, [`models-mcp.md`](../../../posthog_ai/skills/querying-posthog-data/references/models-mcp.md)
carries the property reference and worked query examples.

## The pipeline, and where each stage breaks

1. **Instrument** -> the server emits `$mcp_*` events via the SDK.
   _Breaks:_ handlers not wrapped (`instrument()` is idempotent and degrades to a silent
   no-op on failure); a STDIO server writing to stdout with `console.*` (corrupts the
   protocol stream — wire a `logger`); a disabled or misconfigured posthog-node client.
   For `services/mcp` there is a **single emission path**: `src/hono/analytics.ts` +
   `src/hono/tool-executor.ts` -> `getPostHogClient()` (`src/lib/posthog/client.ts`) ->
   `PostHogMCP`, consumed through the dependency alias `@posthog/mcp-analytics` (the alias
   matters when grepping imports). The legacy MCPcat/AgentCat shim and the transition shim
   that dual-emitted non-`$` `mcp_tool_call` / `mcp_initialize` were both removed and are
   regression-tested in `services/mcp/tests/hono/`. **`services/mcp/ARCHITECTURE.md` still
   describes the old multi-emitter design and references a deleted `lib/mcpcat.ts` — trust
   the source, not that document.**
2. **Ingest** -> events land in ClickHouse `events`. _Breaks:_ ordinary ingestion and quota
   problems; `$session_id` not materialized, which breaks session grouping.
3. **Session list** -> `backend/logic.py::list_mcp_sessions` runs HogQL over a **7-day
   default window** (`DEFAULT_SESSIONS_DATE_FROM`, resolved through `QueryDateRange` with a
   one-day overlap buffer each side) and caches for 30s (`SESSIONS_CACHE_TTL_SECONDS`).
   _Breaks:_ anything outside the window simply isn't there; results can be up to 30s stale.
4. **Charts and tool quality** -> typed `AnalyticsQueryRunner` subclasses in
   `backend/hogql_queries/` (`base.py`, `dashboard_series.py`, `harness_breakdown.py`,
   `tool_quality_tables.py`, `tool_tables.py`), dispatched via the generic `/query/` endpoint
   and enumerated in `backend/facade/queries.py`, with schemas in `posthog/schema.py`.
   Gate: `hogql_queries/base.py::validate_mcp_analytics_access` — the feature flag **plus**
   the `mcp_analytics` RBAC resource. _Breaks:_ flag off, RBAC denies, or Hard rules 1-3
   ignored.
5. **Intent generation** (on demand, per session) -> collect `$mcp_intent` values -> an LLM
   summary of at most two sentences -> Postgres `posthog_mcp_session`. A second,
   project-level path produces the **intent digest / themes** with structured output, bounded
   by `MAX_DIGEST_THEMES`; `resolve_themes()` derives every countable field from the corpus
   so the model cannot invent numbers. Model constants live in `backend/intent_generation.py`.
   _Breaks:_ no `$mcp_intent` captured at all (the agent never filled the injected `context`
   argument and no `intentFallback` was configured), so there is nothing to summarize; LLM
   key or quota problems.
6. **Intent clustering** -> embed (cached in `MCPIntentEmbeddingCache`) -> agglomerative
   clustering (cosine, average linkage, `DEFAULT_DISTANCE_THRESHOLD`) -> JSONB
   `MCPIntentClusterSnapshot`. **Temporal end-to-end, no Celery.** On-demand recompute
   (`trigger_intent_cluster_recompute`, serialized with `select_for_update()` and a
   deterministic per-team workflow id) and the `cluster_mcp_intents` management command both
   start the workflow; the daily run is a Temporal **Schedule**
   (`posthog/temporal/mcp_analytics/intent_clustering/schedule.py`, behind the
   `mcp-analytics-clustering-schedule` flag) that triggers
   `IntentClusteringCoordinatorWorkflow`, which fans out one child workflow per team.
   Two caps will surprise you: `MAX_SNAPSHOT_CLUSTERS` (snapshots keep only the top clusters
   by volume, enforced at write and again at read) and `MAX_QUERY_ROWS`.
   Note the corpus does **not** depend on step 5: `fetch_intent_corpus` takes each session's
   first `$mcp_intent` straight from ClickHouse and only _overrides_ it with the stored LLM
   summary where one exists. So a project can cluster with no generated summaries at all.
   _Breaks:_ empty clusters almost always mean no `$mcp_intent` values in the lookback window
   (check the corpus before chasing summary generation); schedule flag off; stale embeddings.
   Also check the allowlist — `intent_clustering/team_discovery.py` currently returns a
   hard-coded `GUARANTEED_TEAM_IDS = [2]`, so the daily schedule covers only PostHog's own
   project and enabling the flag elsewhere still produces nothing until that changes.
7. **Serve** -> DRF viewsets at
   `/api/projects/{id}/mcp_analytics/{sessions,intent_clusters,feedback,missing_capabilities}`
   (router in `backend/presentation/urls.py`) plus custom actions
   (`sessions/{id}/tool_calls`, `sessions/{id}/generate_intent`, `sessions/intent_digest`,
   `sessions/activity_overview`, `intent_clusters/recompute`). Parallel surface: step 4's
   runners, exposed to agents as the `query-mcp-*` tools.
8. **Frontend** -> Kea scene `MCPAnalyticsScene.tsx`, with tabs enumerated by
   `MCPAnalyticsTab` in `mcpAnalyticsSceneLogic.ts`: activity, dashboard, sessions,
   tool quality, intent clustering, notifications. The landing tab is volume-gated by
   `dashboardStage` in `mcpAnalyticsOnboardingLogic.ts` and applies only to the bare
   `/mcp-analytics` redirect — deep links and explicit tab clicks are never overridden.
   - **Activity** (`earlyData/`): live tool-call feed plus the intent-**themes** card.
     "Theme" (the LLM digest, Activity tab) is **not** "cluster" (the embedding clustering,
     its own tab). Conflating the two is the most common mistake here.
   - **Tool quality** and the per-tool **tool report** (`MCPAnalyticsToolDetail.tsx`, its own
     registered scene): shared date filter, failure-occurrence drill-down with copyable error
     context, and "create fix task" straight into `products/tasks`.
   - **Dashboard**: quill composable `Metric` tiles and `@posthog/quill-primitives`, plus
     **notable sessions** selected by a `NotableRule` — so that table can legitimately be
     short or empty.
   - **Notifications**: first-party destinations for MCP events and recurring AI reports
     (`frontend/notifications/`), thin wiring over the generic hog-function destination and
     subscription machinery.

Postgres models (`backend/models.py`): `MCPSession` (the intent store),
`MCPIntentClusterSnapshot`, `MCPAnalyticsSubmission` (feedback and missing-capability
reports), `MCPIntentEmbeddingCache`.

**Seeding local data:** `./manage.py seed_mcp_sessions --team-id N`
(`backend/management/commands/`), with `--sessions`, `--min-calls`/`--max-calls`, `--days`,
`--missing-capabilities`, `--seed`, and `--clear`. Seeded events are tagged `$mcp_seeded` so
`--clear` removes only seeded data.

## Which repo to change

| Change                                          | Repo                                     | Workflow                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SDK behaviour, events, options, instrumentation | `PostHog/posthog-js`                     | Work in `packages/mcp`. Run its unit tests, build, and lint. **Add a changeset.** Ships to npm; then bump the alias in `services/mcp/package.json` to pick it up.                                                                                                                                                                                                                        |
| Dashboard, queries, clustering, API             | this repo                                | A new chart means a query runner in `backend/hogql_queries/` behind `validate_mcp_analytics_access` — never a SQL template. Obey Hard rules 1-3.                                                                                                                                                                                                                                         |
| A new `query-mcp-*` agent tool                  | this repo (two places)                   | 1) an entry in `products/mcp_analytics/mcp/tools.yaml` with `schema_ref`, `scopes`, `description`, `feature_flag`; 2) the matching `<Name>Query` schema and `<Name>QueryRunner` in `backend/hogql_queries/`; 3) regenerate the tool handlers from `services/mcp` (see its `package.json` scripts). The generic `createQueryWrapper` handles the tool shape — no hand-written TypeScript. |
| PostHog's own dogfood events                    | this repo                                | `services/mcp/src/hono/analytics.ts` + `tool-executor.ts`; client in `src/lib/posthog/client.ts`.                                                                                                                                                                                                                                                                                        |
| Docs                                            | `PostHog/posthog.com`                    | Keep the event and property tables in `contents/docs/mcp-analytics/events.mdx` synced with **both** the TypeScript `constants.ts` and the Python `posthog/mcp/constants.py`.                                                                                                                                                                                                             |
| The install codemod or the wizard command       | `PostHog/context-mill`, `PostHog/wizard` | See [references/wizard-and-onboarding.md](references/wizard-and-onboarding.md) — in particular the rule about which changes need a wizard release and which do not.                                                                                                                                                                                                                      |

**Rule of thumb:** a change to _what gets captured, or how servers are instrumented_ belongs
in the SDKs. _How data is shown, aggregated, or clustered_ belongs in this product. _PostHog's
own dogfood events_ belong in `services/mcp`. A new customer-facing capability usually spans
an SDK plus docs, and the product too if it needs a view.

The wizard install flow, the skill-distribution channels, and the in-app onboarding are all in
[references/wizard-and-onboarding.md](references/wizard-and-onboarding.md).

## Current state

Verified against `master`, `@posthog/mcp` 0.11.7, `posthog` 7.44.0, and MCP spec `2026-07-28`
on 2026-08-25. Treat versions and open threads as perishable: re-check
`packages/mcp/CHANGELOG.md`, the pinned alias in `services/mcp/package.json`, and
[mega-issue 64016](https://github.com/PostHog/posthog/issues/64016) rather than trusting this
section.

**Both SDKs now speak the stateless spec and the v2 MCP SDKs.** `services/mcp` speaks both
dialects at the protocol layer (`src/lib/stateless-protocol.ts` — per-request dialect
detection, `server/discover`, no session minting for modern clients). The TypeScript SDK's
0.10.9-0.11.7 run instruments MCP TypeScript SDK v2 servers (structural detection in
`detect.ts`, both `@modelcontextprotocol` peers optional), resolves client identity and
protocol version through a per-request fallback chain, gates `Mcp-Session-Id` minting on the
revision each request declares, and captures `$mcp_client_user_agent` / `$mcp_vendor_client`.
The Python SDK caught up in `posthog` 7.40.0-7.42.1: MCP Python SDK v2, conversation-anchored
sessions byte-compatible with TS (`derive_session_id_from_conversation`), typed
`$mcp_error_type` / `$mcp_error_message`, and the same UA/vendor capture. The old parity
threads ([posthog-python 803](https://github.com/PostHog/posthog-python/pull/803) and
[830](https://github.com/PostHog/posthog-python/pull/830)) were **closed unmerged and
superseded** — don't cite them as the source of what landed.
[references/stateless-and-sessions.md](references/stateless-and-sessions.md) is the reference
for all of it.

Also shipped: structured intent themes, first-party notification destinations and recurring
reports, `mcp_analytics` access control, the shared `ProductEmptyState` adoption,
failure-occurrence drill-down with "create fix task", the migration of every chart to typed
query runners, the demo seeder, and exec-mode inner-tool breakout (Hard rule 1).

What still lags, all checkable in this repo: the `services/mcp` alias pin is `0.10.2` against a
0.11.7 SDK (Hard rule 5 — no 0.11.x SDK-side fix or SDK-emitted property reaches dogfood data,
though the server independently stamps `$mcp_client_user_agent` and the non-`$`
`mcp_vendor_client` regardless of the pin);
harness resolution does not read the SDK-emitted `$mcp_vendor_client` yet (`HARNESS_TOKEN_SQL`
consumes `$mcp_client_user_agent`, but its top-priority vendor signal is still the
server-stamped non-`$` `mcp_vendor_client`); the exec-property emitter is still absent from
master (Hard rule 1); the clustering schedule still covers only `GUARANTEED_TEAM_IDS = [2]`;
and the product remains behind the `mcp-analytics` flag, so a project without it sees nothing.
