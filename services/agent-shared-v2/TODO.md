# agent-v2 — outstanding work

Lightweight running list of follow-ups across the v2 packages. Each item is
brief — enough context to know what / why / how to start. Cross-cutting
because the work touches multiple services.

---

## A. Old-test parity (gaps vs. the v1 test surface)

### A1. ✓ Queued follow-ups: 3-mid-turn-sends ordering test — done

### A2. ✓ Strict principal match on /send — done (4 tests)

### A3. ✓ /listen SSE lifecycle event emission — done (4 tests)

### A4. ✓ Slack identity / IdentityStore / AgentUser — done (4 tests).

`trusted_workspaces` is now required in the slack trigger config (array or
`"*"`). `MemoryIdentityStore` for tests, `PgIdentityStore` for prod via
`agent_user_v2` table.

### A5. ✓ Log entries — done (4 tests).

`LogSink` interface + `InMemoryLogSink` + `NoopLogSink` + `ClickHouseLogSink`
stub. Runner mirrors every lifecycle event into the sink. `ClickHouseLogSink`
needs Kafka wiring before it can hit production CH; that's a follow-up
(see C7 below).

---

## B. Domain-correctness follow-ups (we built it, but not finished)

### B1. Dynamic skill loading via tool

**Current**: `buildSystemPrompt()` inlines every skill in `spec.skills` into
the system prompt at session start. Long skills blow up token usage on
every turn even when irrelevant.

**Desired**: skills are exposed as one tool, `meta.load_skill.v1`, with
arguments `{ id: string }`. The system prompt lists available skills as
`{ id, description }` pairs (a few tokens each). The model calls
`load_skill({ id })` only when it needs the body; the tool returns the
markdown.

This is **our concern, not pi-ai's**. pi-ai has no "dynamic context"
concept — it's a one-shot model invoker. We implement the tool ourselves
in `services/agent-tools/src/tools/meta.ts` and update
`buildSystemPrompt()` to emit the skill index instead of inlining bodies.

Skill files in the bundle stay the same — the tool reads them from
`bundle.readText(rev_id, skill.path)` at call time.

Where:

1. New native tool `meta.load_skill.v1` in agent-tools/meta.ts.
2. `system-prompt.ts` switches to emitting the skill INDEX (one line per
   skill: `- <id>: <description>`).
3. Add `description` field to `SkillRef` in spec (currently just `id` +
   `path`).
4. Tool implementation reads the bundle (needs `bundle` in `ToolContext`
   or a side-channel; cleanest: pass bundle through worker → tool ctx).

Tests:

- Single-skill agent: system prompt contains the description, NOT the body.
  Faux model calls `load_skill`, tool returns the body, agent uses it.
- Unknown skill id → tool returns an error tool_result.
- Real-inference variant: model with a "research" skill chooses to call
  `load_skill` when relevant and ignores it otherwise.

### B2. Wire provider routing through PostHog's llm-gateway

Production model traffic goes through `services/llm-gateway` — one PostHog
gateway key per deployment, not per-team API keys. `AGENT_USE_LLM_GATEWAY=1`
already flips the runner to route every spec.model through
`posthogLlmGatewayModel()`. Default this on for staging+prod; keep direct
provider calls available for local dev / real-inference tests via the
ANTHROPIC_API_KEY / OPENAI_API_KEY paths. No per-team key resolution
needed — gateway handles tenancy.

### B3. Real Docker sandbox host image

`sandbox-docker.ts` ships the shell-out skeleton. Missing: the in-container
node host (`/sandbox/host.js` + `/sandbox/dispatch.js`) that loads compiled
tools and dispatches invokes. Plus the Dockerfile + a published image.

Where: new `services/agent-sandbox-host/` package with the host node code;
Dockerfile in same dir; CI step to publish to ghcr.

### B4. Modal sandbox real impl

Stub at `sandbox-modal.ts`. Replace with real Modal sandbox provisioning
when a Modal-backed deployment is wanted.

### B5. Agent-mgmt MCP wired into services/mcp

`agent-mgmt-mcp` package exists with all handlers + zod schemas. Not yet
plugged into `services/mcp`'s TOOL_MAP / toolDefinitions YAML pipeline /
scopes. Without this, agents can't be authored via MCP yet.

Where: register `agent_mgmt:*` handlers under the existing tool framework
in `services/mcp/src/tools/`. Each handler becomes a factory like the
other tools.

---

## C. Refactor sequencing (from docs/native-refactor.md)

### C1. Django migration for v2 tables

`products/agent_stack/backend/models_v2.py` defines the models but the
migration hasn't been generated. Generate + apply when ready to wire the
real backend. Also add Django models for `agent_user_v2` (new this
iteration).

### C2. Step 9 cutover

Once v2 is at parity: delete `services/agent-ingress`, `agent-runner`,
`agent-janitor`, `agent-tests`; rename the `-v2` siblings to drop the
suffix. One mechanical pass.

### C3. Slack @agent-builder bot (step 10)

Build an agent in this system that drives the `agent_mgmt:*` tools to
author other agents.

### C4. Frontend wizard scene (step 11)

`/agents/new` in PostHog, MCP client of `agent_mgmt:*`.

### C5. Library tables (step 12)

`SkillTemplate` + `CustomToolTemplate` for canonical edit-once-import-many.
Authoring-guide migrates from in-repo string to a `SkillTemplate` row.

### C6. MCP-sourced tools — `spec.mcps[]` runtime handling (step 13)

The data model already has `spec.mcps`. Runner side: open MCP clients to
each entry, namespace-prefix tool names, route calls back.

### C7. ClickHouseLogSink — real Kafka writer

`ClickHouseLogSink` is a stub that throws on `write()`. Production needs:
(a) a Kafka client (node-rdkafka or @platformatic/kafka), (b) the
`log_entries` topic schema agreed with the consumer side, (c) a
materialized-view setup in CH that reads the topic. The runner's call
site is unchanged once this lands.

---

## D. Stretch / polish

- ✓ ~~`spec.model` per-agent wiring~~ — done
- ✓ ~~Real-inference suite (custom tool, multi-turn, max_turns ceiling)~~ — done (5 tests)
- ✓ ~~Worker-resume + claim TTL~~ — done
- Per-process `concurrency` env knob is in place; tune defaults once we have
  load data.
- Sandbox A/B routing between Modal and Hogland-native — design when both
  exist.
