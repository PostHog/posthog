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

### B2. Wire provider routing through PostHog's llm-gateway — DEFERRED

`services/llm-gateway` doesn't exist yet, so there's nothing to default to.
The runner already accepts the override (`AGENT_USE_LLM_GATEWAY=1` →
`posthogLlmGatewayModel()`), keep that available. Revisit and flip the
default once the gateway is live.

### B3. Real Docker sandbox host image

`sandbox-docker.ts` ships the shell-out skeleton. Missing: the in-container
node host (`/sandbox/host.js` + `/sandbox/dispatch.js`) that loads compiled
tools and dispatches invokes. Plus the Dockerfile + a published image.

Where: new `services/agent-sandbox-host/` package with the host node code;
Dockerfile in same dir; CI step to publish to ghcr.

### B4. Modal sandbox real impl

Stub at `sandbox-modal.ts`. Replace with real Modal sandbox provisioning
when a Modal-backed deployment is wanted.

### B5. Agent authoring surface — deferred

`agent-mgmt-mcp` will be reworked as a follow-up; the current package
shape is not the direction we'll ship. Don't wire it into `services/mcp`
yet — leave the v1 mgmt path in place until we redesign this.

### B6. Redis pubsub bus (CRITICAL — cutover blocker)

v1 has `RedisSessionBus` (`services/agent-core/src/pubsub/redis.ts`) used
by ingress for cross-process /listen SSE. v2's `bus.ts` only ships
`MemorySessionEventBus` + `NoopSessionEventBus`, so a session running on
worker A can't be observed by an SSE client connected to ingress B.

Where: new `RedisSessionEventBus` in `agent-shared-v2/src/bus.ts`
implementing the same `SessionEventBus` interface. Wire it in
`agent-ingress-v2`/`agent-runner-v2` entrypoints when `REDIS_URL` is set;
fall back to memory otherwise. Reuse the v1 channel naming
(`session:<id>`) so any existing tooling still works.

### B7. EncryptedFields for Django env decryption (CRITICAL — cutover blocker)

v1's runner decrypts `AgentApplication.encrypted_env` via
`EncryptedFields` (Fernet, key rotation) — see
`services/agent-core/src/encryption/index.ts` and the wire-up in
`agent-runner/src/lib.ts:85`. v2's `SecretBroker` only handles
nonce/redaction at tool dispatch, not at-rest decrypt.

Where: vendor `EncryptedFields` into `agent-shared-v2/src/encryption.ts`
(copy is fine — small, stable, already once-copied from cdp). Use it in
the worker's `resolveSecrets()` resolver when reading from the real
Django table.

### B8. Prior session log loading from ClickHouse on resume — DEFERRED, needs design

Neither v1 nor v2 currently does this. The Kafka sink we have writes the
audit log; the read side (rehydrating a resumed session's prior tool
calls + assistant text from `log_entries` into the pi-ai message stream)
is unbuilt. **This needs proper thought before we pick an approach** —
key questions:

1. Source of truth: today the session row's `conversation` JSONB is the
   source of truth on resume. If CH becomes a second source we need a
   clear rule for when each wins (and how to handle divergence).
2. Compression / windowing: full audit replay is the wrong default for
   long-running sessions — we'll need a window or a summarization step.
3. Schema fit: `log_entries` is event-shaped, the runner wants
   `Message[]`. The mapping is lossy in both directions — we either pin
   richer schema in the events, or accept the loss.
4. Trigger semantics: do we replay on every resume, or only when the
   session row was lost / truncated? What does the user perceive?

Don't implement before agreeing on the answers above.

### B9. Durable sandbox-instances tracking

v1 has `SandboxInstancesRepository`
(`services/agent-core/src/posthog-db/sandbox-instances.ts`) + a
`SandboxTracker` that writes provisioning → ready → terminated rows to
`agent_sandbox_instances`. Plus a sandbox-janitor that reaps stale rows.
v2 has provider impls (`sandbox-{docker,modal,inprocess}.ts`) but no
durable state — no cross-process view of which sandboxes are live.

Where: new `sandbox-instance-store.ts` in `agent-shared-v2` mirroring
v1's interface; new table in `pg-schema.ts`; the sandbox pools call into
the store at provisioning/teardown.

### B10. Poison-pill detection in janitor

v1's janitor distinguishes stuck-but-recoverable from broken via a touch
counter — fail after 3+ stalls (`agent-core/src/queue/janitor.ts:79`).
v2's `sweep.ts` only single-shot re-queues stuck running and fails
24h-stale waiting; nothing stops a bad job from re-queueing forever.

Where: add `retry_count INT DEFAULT 0` to `agent_session_v2`; bump it on
each `reapStuckRunning`; promote to `failed` past a threshold.

### B11. `posthog.feature_flags.evaluate` builtin

v1 has it as a runner builtin
(`services/agent-runner/src/tools/builtins.ts:23` and
`agent-core/src/builtins/index.ts:33`). Missing from v2's
`agent-tools/src/tools/`.

Where: new `posthog-feature-flags-evaluate.ts` in `agent-tools/src/tools/`
calling the same backend as v1.

### B12. Timing instrumentation helpers

v1 has `withTiming` / `withTimingSync`
(`services/agent-core/src/instrumentation/timing.ts`) emitting structured
`event: 'timing'` logs around bundle fetch, sandbox lifecycle, LLM
turns. v2's runner has no per-stage latency observability.

Where: port the helper into `agent-shared-v2/src/timing.ts`; wrap the
hot paths in `agent-runner-v2/src/run-turn.ts` and the bundle-fetch
path.

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

Build an agent in this system that authors other agents — blocked on the
authoring surface (B5).

### C4. Frontend wizard scene (step 11)

`/agents/new` in PostHog — blocked on the authoring surface (B5).

### C5. Library tables (step 12)

`SkillTemplate` + `CustomToolTemplate` for canonical edit-once-import-many.
Authoring-guide migrates from in-repo string to a `SkillTemplate` row.

### C6. MCP-sourced tools — `spec.mcps[]` runtime handling (step 13)

The data model already has `spec.mcps`. Runner side: open MCP clients to
each entry, namespace-prefix tool names, route calls back.

### C7. KafkaLogSink — production wire-up

`KafkaLogSink` is implemented (ports v1's `agent-core/log-entries/producer.ts`
— rdkafka HighLevelProducer, fire-and-forget produce, snappy compression,
lazy native import). Outstanding to ship:
(a) wire it into `agent-runner-v2/src/index.ts` when `KAFKA_BROKERS` is
set (Noop otherwise), (b) confirm the `log_entries` topic + CH
materialized view exist in target deployments (same as v1 — no schema
change), (c) once enabled in staging, verify rows land in CH end-to-end.

---

## D. Stretch / polish

- ✓ ~~`spec.model` per-agent wiring~~ — done
- ✓ ~~Real-inference suite (custom tool, multi-turn, max_turns ceiling)~~ — done (5 tests)
- ✓ ~~Worker-resume + claim TTL~~ — done
- Per-process `concurrency` env knob is in place; tune defaults once we have
  load data.
- Sandbox A/B routing between Modal and Hogland-native — design when both
  exist.
