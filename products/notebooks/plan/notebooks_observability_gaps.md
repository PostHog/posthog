# Notebooks usage observability — gap analysis & instrumentation plan

Goal: instrument Notebooks so we (PostHog, dogfooding) can answer real usage questions
from our own event stream. Today the telemetry is frontend-only and missing the three
load-bearing events: **open/view**, **share**, and **origin-attributed create**.

All findings below reference `master` as of this doc's creation.

## The questions we want to answer

1. Do people **re-visit** their notebooks?
2. Do people **share** their notebooks?
3. Do people visit **others'** notebooks?
4. How often do **PostHog Code / Max** create notebooks?
5. How often do people create notebooks via **their own clients (MCP)**?
6. What kinds of **problems/questions** start in AI/MCP/Code and end up in notebooks?

## Verdict: none are cleanly answerable today

| #   | Question                       | Answerable now? | Blocking gap                                                                                                                                                                                                                      |
| --- | ------------------------------ | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Re-visit own notebooks         | ❌              | No open/view event exists anywhere                                                                                                                                                                                                |
| 2   | Share notebooks                | ❌              | No analytics event on actual share/enable/grant (only an interest CTA + activity-log rows)                                                                                                                                        |
| 3   | Visit others' notebooks        | ❌              | No view event; no owner-vs-viewer property on any event                                                                                                                                                                           |
| 4   | Max / PostHog Code create rate | ❌              | `notebook created` is origin-agnostic; Max backend path emits no event. PostHog Code creates via the MCP `notebooks-create` tool, so it shares the MCP path with Q5 — `creation_source: mcp` alone won't separate them (see note) |
| 5   | MCP create rate                | ❌              | MCP `notebooks-create` → DRF create → activity-log row only, no analytics event, no source marker                                                                                                                                 |
| 6   | Problems → notebook            | ⚠️ DB-join only | Link exists via `short_id`→`AgentArtifact.conversation`→`Conversation.topic`, but not in event stream; fragile; absent for MCP                                                                                                    |

## Current state (what exists today)

### Frontend telemetry (the only analytics that exists)

All direct `posthog.capture(...)`; **no** `eventUsageLogic` involvement.

- `notebook created` — `frontend/src/models/notebooksModel.ts:129` — props: `{ short_id }` only.
  Also fires `addProductIntent({ product_type: NOTEBOOKS, intent_context: NOTEBOOK_CREATED })`.
- `notebook duplicated` — `frontend/src/scenes/notebooks/Notebook/notebookLogic.ts:893` — `{ short_id }`
- `notebook content changed` — `notebookLogic.ts:1761` — `{ short_id }`
- `notebook markdown merge conflict` — `notebookLogic.ts:1482` — `{ short_id, conflict_count }`
- node-level: `notebook node added` (`Nodes/NodeWrapper.tsx:542`), `notebook node created`
  (`Nodes/utils.tsx:150`), `notebook node expanded` (`Nodes/notebookNodeLogic.ts:1339`),
  `notebook node dropped` (`DropAndPasteHandlerExtension.tsx:144`), title add/edit events.
- paste/drop: `notebook files dropped/pasted`, `notebook table pasted`, `notebook markdown pasted`.
- `notebook containing filter applied` — `NotebooksTable/ContainsTypeFilter.tsx:65`
- `pressed interested in notebook sharing` — `Notebook/NotebookShareModal.tsx:43` —
  **interest CTA, NOT an actual share.**

Missing on the frontend: **any open/view event.** `loadNotebookSuccess`
(`notebookLogic.ts:1844`), `notebookSceneLogic`, `notebookPanelLogic`, `openNotebook` fire
zero captures.

### Backend creation paths (all emit NO analytics event)

Choke points: the four helpers in `products/notebooks/backend/logic.py`
(`create_notebook`, `aupsert_notebook`, `create_group_notebook`, `create_account_notebook`)
and `NotebookSerializer.create` (`products/notebooks/backend/presentation/views/notebook.py:173`).

| Path | Trigger                       | Location                                                                 | Analytics | Activity log                              |
| ---- | ----------------------------- | ------------------------------------------------------------------------ | --------- | ----------------------------------------- |
| 1    | Human UI / REST               | `notebook.py:173-206`                                                    | none      | `log_notebook_activity("created")` `:197` |
| 2    | MCP `notebooks-create`        | same as 1 (`mcp/tools.yaml:33`)                                          | none      | same as 1                                 |
| 3    | Max `create_notebook` tool    | `ee/hogai/tools/create_notebook/helpers.py:105-192` (`aupsert_notebook`) | **none**  | **none**                                  |
| 4    | Max `upsert_account_notebook` | `products/customer_analytics/backend/max_tools.py:403`                   | none      | none                                      |
| 5    | Anomaly investigation agent   | `posthog/temporal/ai/anomaly_investigation/workflow.py:149`              | none      | none                                      |
| 6    | Group notebook auto-create    | `ee/clickhouse/views/groups.py:873`                                      | none      | none                                      |

The `Notebook` model (`products/notebooks/backend/models.py:19-64`) has **no origin/source
field**. AI-created notebooks are attributed to the human user Max acts for and are
indistinguishable from hand-created ones.

### Sharing (no analytics event on any real share action)

- Public link: `SharingConfigurationViewSet` enable/disable at `posthog/api/sharing.py:463-560`;
  token refresh `:562-621`. Only `log_activity(scope="Notebook", "sharing enabled|disabled")`
  `:533-554` and `"access token refreshed"` `:605-618` — activity log, not analytics.
- RBAC grants: `ee/api/rbac/access_control.py` — zero `capture`/`report_user_action`.
- The only sharing analytics is the frontend interest CTA above.

### AI → notebook linkage (structural, not in event stream)

`Notebook.short_id` → `AgentArtifact.short_id` (`ee/hogai/tools/create_notebook/helpers.py:124,181`)
→ `AgentArtifact.conversation` FK (`products/posthog_ai/backend/models/assistant.py:340`)
→ `Conversation.topic` (classified from first question, `assistant.py:57-88`).
Breaks if the artifact/conversation is deleted. MCP path has no conversation at all.

### ⚠️ Note on "PostHog Code" vs generic MCP clients (Q4 vs Q5)

PostHog Code creates notebooks **via the MCP `notebooks-create` tool** — it is itself an MCP
client. So it flows through the same path as Q5 (a customer's own MCP client), and a plain
`creation_source: mcp` property cannot tell the two apart. To split Q4 from Q5 we need a
**client identifier** on the create event, e.g.:

- the auth principal (personal API key vs project secret key vs OAuth app) used for the call, and/or
- the MCP client name / user-agent (PostHog Code should send an identifiable client id).

Action: when emitting the server-side `notebook created` event, capture `mcp_client` /
`api_key_type` (or an `agent`-tagged sub-source like `mcp_posthog_code`) so PostHog Code is
distinguishable from third-party MCP usage. Confirm PostHog Code sends a stable client id;
if not, that's a prerequisite fix.

## Root cause

Instrumentation is frontend-only, but Q4/Q5/Q6 are **server-side flows that never touch the
browser** (Max, MCP, Temporal). The frontend `notebook created` event literally cannot see
them. The fix must put capture at the **server-side creation choke point**, plus add a few
frontend events for view/share.

## Proposed instrumentation

### A. Server-side `notebook created` (covers Q4, Q5, Q6)

Emit one analytics event at the facade choke point so every path is covered uniformly.
Prefer a single emission site — either in the `logic.py` helpers or in `NotebookSerializer.create`
plus the two Max tools + Temporal + group paths that bypass the serializer.

Event: `notebook created` (server-side)
Properties:

- `short_id`
- `creation_source`: `ui | mcp | max_ai | max_account_notebook | temporal_agent | group_auto`
  - `mcp` vs `ui`: distinguish by auth type / user-agent in the DRF request context.
  - `max_ai` / `max_account_notebook` / `temporal_agent` / `group_auto`: pass an explicit
    source arg into the facade helper from each caller.
- `mcp_client` / `api_key_type` (when `creation_source = mcp`): identify the calling client so
  **PostHog Code** (Q4) is separable from a customer's own MCP client (Q5). See the PostHog
  Code note above — plain `creation_source: mcp` is not enough to split Q4 from Q5.
- `conversation_id`, `topic`: set when `creation_source` is AI-originated (from the
  `AgentArtifact.conversation` on the Max path). Closes Q6 in the event stream.
- `visibility`, `node_count` (optional context).

**Resolved: keep both, with distinct event names.**
The hazard is that a human UI create fires two `notebook created` rows for one logical
creation (browser at `notebooksModel.ts:129` + the new server-side one at DRF `create`),
while Max/MCP/Temporal/group creates fire only the server event — so a naive
`count(notebook created)` becomes `(UI creates × 2) + (non-UI creates × 1)`, over-representing
UI creation.

Resolution:

- Server-side `notebook created` is the **single source of truth** for counts and cross-path
  attribution (`creation_source`, `mcp_client`, conversation/topic).
- **Rename** the frontend capture to a client-scoped name (e.g. `notebook created (client)`)
  so it survives as the UI-context / session-replay funnel event. Distinct names make
  double-counting structurally impossible — no reliance on query-time filtering.
- Keep `addProductIntent(...)` (`notebooksModel.ts:133`) as-is regardless — it is activation
  tracking, not the analytics event.

Why not just delete the frontend event: the browser event carries context the server-side
Python capture cannot reconstruct — `$session_id`/`$window_id` (session-replay linkage to the
actual creation session), `$current_url`/`$referrer` (which UI surface created it: dashboard vs
tree vs scene — the server only sees `POST /notebooks`), active `$feature/*` flag enrollment,
same-session funnel continuity with `notebook content changed` / `notebook node added`, and
device/browser/geo autocapture. Deleting it loses all of that.

Belt-and-suspenders if both must share a name later: both events carry `short_id` (a natural
idempotency key), so `count(distinct short_id)` makes double-emission harmless — but the
distinct-name approach above is preferred and needs no such discipline.

### B. Sharing events (covers Q2)

- `notebook sharing enabled` — at `posthog/api/sharing.py` enable path. Props: `short_id`,
  `share_type: public_link`, `has_password`.
- `notebook access granted` — at the RBAC grant path. Props: `short_id`, `access_level`,
  `grantee_type` (user/role).

### C. Frontend `notebook opened` (covers Q1 + Q3 in one event)

Emit in the load path (`loadNotebookSuccess` / `notebookSceneLogic`).
Properties:

- `short_id`
- `is_creator`: `notebook.created_by?.uuid === user.uuid` — own vs someone else's
- `user_access_level`
- `access_source`: `direct | shared_link`
- `node_count`

### D. Optional / durable

- Add a `creation_source` field to the `Notebook` model (Django migration) so attribution
  survives conversation/artifact deletion and is queryable in Postgres, not just events.
- `notebook viewed via shared link` on the anonymous `SharingViewerPageViewSet`
  (`posthog/api/sharing.py:1202`) for external-view counting.

## Implementation plan

Ordered as four independently-shippable PRs, earliest-signal-first so each merge unblocks a
question on its own. PR 1 is pure additive frontend (lowest risk); PR 2 carries the
double-count resolution and is the largest.

### Preconditions / conventions

- **Event-name constants.** Add the new event names as constants in one place the product
  owns (e.g. `products/notebooks/backend/analytics.py` for server-side, and a matching
  frontend constant) rather than string literals, so FE/BE names can't drift.
- **Server-side transport.** Use `report_user_action` (`posthog/event_usage.py:396`) for
  request/user-context paths (UI/MCP) — it already handles `SyntheticUser` (project-secret
  API keys) and pulls request analytics props. For **Temporal / Celery** paths use
  `ph_scoped_capture` (`posthog/ph_client.py:63`) — a plain `posthoganalytics.capture()` in
  those workers is silently dropped (see root `CLAUDE.md`).
- **Skill gate.** Any serializer/viewset edit here must go through `/improving-drf-endpoints`
  first (see `.claude/rules/drf-endpoints.md`).
- **Isolation.** Emit at the product boundary (serializer + facade functions), not deep in
  `logic.py` domain helpers — cross-product callers (Max, groups) already reach notebooks via
  `facade.api`, so that is the natural single owner of emission.

### PR 1 — Frontend `notebook opened` (unblocks Q1 + Q3)

Additive, no double-count risk.

**Scope: human / browser opens only.** This event is deliberately client-side so it answers the
human-behavior questions (revisit own, view others') cleanly and carries browser context
(`$session_id`, replay linkage, referrer). Programmatic reads (MCP, API clients) are **not**
this event — they are the server-side `notebook read` in PR 2e. Keeping them apart is the same
discipline as the `created` split: folding agent reads in here would inflate "revisits" and make
Q1/Q3 unanswerable.

- [x] Emit `posthog.capture('notebook opened', …)` in the load path — `loadNotebookSuccess`
      (`frontend/src/scenes/notebooks/Notebook/notebookLogic.ts`). Gated once per mount via a
      `cache.hasCapturedOpen` flag (the listener also runs on every polling refresh); the flag
      resets on remount, so revisiting counts as a fresh open. Scratchpad and template notebooks
      are excluded.
- [x] Properties: `short_id`, `is_creator` (`notebook.created_by?.uuid === user.uuid`),
      `user_access_level`, `access_source` (`direct | shared_link`), `node_count`.
- [x] Payload/exclusion logic extracted to a pure helper `buildNotebookOpenedEvent`
      (`notebookAnalytics.ts`) and unit-tested (`notebookAnalytics.test.ts`) — covers is_creator
      own/other, shared-vs-direct, scratchpad/template/no-notebook skips, and null content/creator.
      The once-per-mount gate stays in the listener (trivial one-liner, not worth a full-mount test).

### PR 2 — Server-side `notebook created` + FE rename (unblocks Q4/Q5/Q6; resolves double-count)

This is the resolution from section A above — ship the two halves together so counting is
never briefly double-counted on `master`.

**Emission lives in two layers, not at every caller.** All server/background paths already
funnel through the four create functions in the facade `api.py` — so capture goes _inside_
those functions and every workflow/viewset that calls them is covered automatically. Callers
only ever pass a `creation_source`; they never build a capture call. The only path that
bypasses the facade is the DRF serializer, and it stays separate because `ui` vs `mcp` needs
the `request` auth context the facade cannot see.

**2a. Shared capture helper** (`products/notebooks/backend/analytics.py`, new)

- [ ] `capture_notebook_created(*, notebook, creation_source, user=None, request=None, team=None, extra=None)`.
      Picks the transport: `report_user_action` when `request`/`user` present (serializer path);
      `ph_scoped_capture` for the request-less facade/background paths.
- [ ] Properties per section A: `short_id`, `creation_source`
      (`ui | mcp | max_ai | max_account_notebook | temporal_agent | group_auto`),
      `mcp_client` / `api_key_type` (from `request.successful_authenticator` + user-agent when
      `creation_source = mcp`), `conversation_id` + `topic` (AI paths), optional `visibility`,
      `node_count`.

**2b. Emit inside the four facade create functions** (`facade/api.py`) — covers Q4/Q5/Q6
server paths with zero per-workflow instrumentation.

- [ ] `create_notebook` (`api.py:142`) — add a `creation_source` param (default e.g.
      `"server"`); emit after `logic.create_notebook` returns. The anomaly Temporal workflow
      (`posthog/temporal/ai/anomaly_investigation/workflow.py:149`) then only passes
      `creation_source="temporal_agent"` — a single kwarg, no capture code in the workflow.
- [ ] `aupsert_notebook` (`api.py:122`) — emit **only when `created` is True** (aupsert also
      updates). Default source `max_ai`; the Max `create_notebook` tool passes
      `conversation_id`/`topic` from the `AgentArtifact.conversation` so Q6 is closed here.
- [ ] `create_group_notebook` (`api.py:192`) — default source `group_auto`. `_create_notebook_for_group`
      (`ee/clickhouse/views/groups.py:873`) needs **no change**.
- [ ] `create_account_notebook` (`api.py:196`) — default source `max_account_notebook`; the Max
      account tool (`products/customer_analytics/backend/max_tools.py:403`) needs no change.
- [ ] These functions take ids, not `Request`, and several run inside `transaction.atomic`
      (group/account) or a Temporal activity — so route their capture through `ph_scoped_capture`,
      and for the transactional paths fire on `transaction.on_commit` to avoid a phantom event if
      the outer request rolls back.

**2c. Serializer (the one non-facade path)** — `NotebookSerializer.create`
(`presentation/views/notebook.py:190`)

- [ ] After the `log_notebook_activity` call, emit with source derived from `request`: `mcp`
      when the authenticator is an API key / OAuth app, else `ui`; include `mcp_client` /
      `api_key_type` for the `mcp` case. Uses `report_user_action` (has request + user).
- [ ] Optional cleanup (own follow-up, not required): route this create through
      `facade.api.create_notebook` so the raw `Notebook.objects.create` at `:190` disappears and
      there is a single create entry point. Deferred because the serializer does extra work
      (`annotate_python_nodes`, `short_id` validation) and needs the request for `ui`/`mcp`.

**2d. Frontend rename (kills the double-count)**

- [ ] Rename the browser capture at `frontend/src/models/notebooksModel.ts:129` from
      `notebook created` to a client-scoped name (e.g. `notebook created (client)`). Keep its
      `short_id` prop and **keep `addProductIntent(...)` at `:133` untouched** — it is activation
      tracking, not the analytics event.
- [ ] Update any saved insights / dashboards that count `notebook created` to point at the
      server-side event (note this in the PR description for the product team).

**2e. Server-side `notebook read` (agent / programmatic access)** — the read counterpart to the
`created` split. Answers "how often do MCP / API clients read notebooks?" and closes the loop
"are AI-created notebooks later consumed by agents?" — a signal none of Q1–Q6 capture.

There are **three distinct ways an agent can read a notebook**, and they do not share a choke
point — this is important, because instrumenting only the REST endpoint silently misses two of
them:

1. **REST retrieve** — MCP `notebooks-retrieve` (op `notebooks_retrieve`, "Get notebook") and
   `notebooks-list` (op `notebooks_list`) both exist and return the full `content`. They flow
   through `NotebookViewSet.retrieve` (`notebook.py:613`). **← what 2e captures.**
2. **HogQL / SQL** — the `notebooks` system table (`posthog/hogql/database/schema/system.py:1225`,
   maps to `posthog_notebook`, `access_scope="notebook"`) exposes `content` **and** `text_content`
   as queryable columns. So `SELECT content, text_content FROM notebooks WHERE short_id = …` reads
   the entire body via the query engine — reachable from Max's SQL tool, the MCP query tool, or any
   query API. **This bypasses the REST endpoint entirely** and 2e does **not** see it (see gap
   below).
3. **Max artifact handler** — `NotebookHandler.alist` (`ee/hogai/artifacts/handlers/notebook.py:47`)
   reads from the **`AgentArtifact` table, not `posthog_notebook`** (docstring: "Notebooks are only
   stored in the ARTIFACT source"). This is Max re-reading its _own artifact snapshot_, not the live
   product notebook — a different signal, intentionally **out of scope** for `notebook read`.

Instrumentation:

- [ ] Emit `notebook read` at the DRF **retrieve** endpoint (`notebook.py:613`), **gated to
      non-session auth**. Session-cookie requests are the browser and are already covered by PR 1's
      `notebook opened` — skip them here to avoid double-counting the frontend's own fetch. Reuse
      the same authenticator classification helper as the `ui` vs `mcp` split in 2c.
- [ ] Properties: `short_id`, `read_source` (`mcp | api`), `mcp_client` / `api_key_type`
      (from `request.successful_authenticator` + user-agent), `is_creator`, `user_access_level`.
- [ ] Scope to single-notebook retrieve. `notebooks-list` is a browse/discovery action with
      different intent and cardinality — leave it out of `notebook read` (capture separately later
      if list usage becomes a question).
- [ ] **Do not** capture at the facade `get_notebook` / `aget_notebook` — those are called for
      permission checks (`logic.acan_user_edit_notebook`) and Max's dedup existence-check
      (`ee/hogai/tools/create_notebook/helpers.py:124`), so capturing there would fire constantly
      on internal machinery, not intentful reads.

**Known gap — the SQL read path is not covered.** An agent that pulls a notebook via
`SELECT … FROM notebooks` (path 2) produces no `notebook read` event, so agent-consumption counts
from 2e are a **lower bound**. Capturing it would mean inspecting executed HogQL for a reference to
the `notebooks` table in the query pipeline — higher effort, noisier (joins, `count()` over the
table, permission-driven scans), and easy to over-count. Deferred; call it out explicitly in the PR
so the metric is read as "REST/MCP reads," not "all agent reads." If SQL-based reads turn out to
matter, the cleanest follow-up is a dedicated marker in the query layer when the `notebooks` table
is selected from — not a broadening of 2e.

Verification for PR 2: create one notebook through each of the six paths and confirm exactly
one server-side `notebook created` per creation with the right `creation_source`, and that a
UI create no longer produces two `notebook created` rows. For 2e: an MCP retrieve emits one
`notebook read` with `read_source: mcp`, while opening the same notebook in the browser emits
`notebook opened` (PR 1) and **no** `notebook read`.

### PR 3 — Sharing events (unblocks Q2)

- [ ] `notebook sharing enabled` — `SharingConfigurationViewSet` enable path
      (`posthog/api/sharing.py:463-560`, next to the `log_activity` at `:533`). Props: `short_id`,
      `share_type: public_link`, `has_password`. Emit on the enable transition only, not on
      idempotent re-saves.
- [ ] `notebook access granted` — RBAC grant path (`ee/api/rbac/access_control.py`). Props:
      `short_id`, `access_level`, `grantee_type` (`user | role`). Guard the viewset edits with
      `/improving-drf-endpoints`.

### PR 4 — Optional durability

- [ ] Add a `creation_source` field to the `Notebook` model (Django migration via
      `/django-migrations`) so AI attribution survives conversation/artifact deletion and is
      queryable in Postgres. Backfill is not required — new rows only.
- [ ] `notebook viewed via shared link` on the anonymous `SharingViewerPageViewSet`
      (`posthog/api/sharing.py:1202`) for external-view counting.

### PR 5 — Optional: SQL read path for `notebook read` (closes the 2e gap)

Covers the read surface 2e cannot see — agents pulling notebook bodies via
`SELECT content, text_content FROM notebooks` against the `notebooks` HogQL system table
(`posthog/hogql/database/schema/system.py:1225`), which bypasses the REST endpoint entirely.

**Prerequisite (not done here): analyze overall SQL access metrics first.** Before instrumenting,
understand how notebook-table reads sit within general HogQL/query usage — volume, who runs them
(Max vs MCP query tool vs API), and how to separate an intentful body read from incidental scans
(`count()`, joins, permission-driven access). That analysis decides whether a per-table read event
is even meaningful or just noise. Scope it as its own investigation.

- [ ] (After the analysis) Emit `notebook read` with `read_source: sql` from the query layer when
      an executed HogQL query selects from the `notebooks` table. Mark it clearly so REST/MCP vs SQL
      reads stay separable and 2e's headline metric is not silently redefined.
- [ ] Guard against over-counting: exclude `count()`-only / metadata scans and permission-check
      queries; ideally fire only when `content` / `text_content` columns are actually projected.

### Coverage check (map back to the questions)

| Question                                               | Unblocked by                                                                                                                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1 re-visit own                                        | PR 1 (`is_creator = true` on `notebook opened`)                                                                                                                       |
| Q2 share                                               | PR 3                                                                                                                                                                  |
| Q3 visit others'                                       | PR 1 (`is_creator = false`)                                                                                                                                           |
| Q4 Max / PostHog Code create                           | PR 2 (`creation_source` + `mcp_client`/`api_key_type`)                                                                                                                |
| Q5 MCP create                                          | PR 2 (`creation_source = mcp`)                                                                                                                                        |
| Q6 problems → notebook                                 | PR 2 (`conversation_id` + `topic` on AI paths)                                                                                                                        |
| Q7 agents read notebooks (+ AI-created consumed later) | PR 2e (`notebook read`, `read_source`) — REST/MCP reads, a lower bound; SQL `SELECT FROM notebooks` reads deferred to optional PR 5 (needs SQL-access analysis first) |
