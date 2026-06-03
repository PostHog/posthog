# agent-runner — Worker loop for the v2 agent platform

The session executor. Claims from the queue, loads revision + bundle,
drives pi-agent-core's agent loop, dispatches tools, persists
conversation, publishes lifecycle events.

You will almost always need the broader platform in your head — read
[docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md)
first.

## What lives here

- [src/loop/](src/loop/) — the session execution: `driver.ts` (drives
  pi-agent-core's `runAgentLoop`, translates its event stream into the
  bus/log/analytics sinks + persistence + outcome), `build-agent-tools.ts`
  (native / custom / meta tools as `AgentTool[]`), `approval.ts` (gated
  queue + resume), `provider-safe-names.ts`.
- [src/workers/](src/workers/) — the outer `Worker` (claim → runOne →
  loop), concurrency, shutdown.
- [src/resolvers/](src/resolvers/) — secrets, integrations, model
  selection. Each is a function the caller can override; the harness
  and prod wire different concrete impls.
- [src/models/](src/models/) — model resolution (`resolveModel`) + the
  ai-gateway model factory. The driver streams through pi-ai's
  `streamSimple` directly; there is no client wrapper.
- [src/index.ts](src/index.ts) — prod bin entry. Reads env, wires
  real PG pools + KafkaLogSink + RedisSessionEventBus, starts the loop.
- [src/lib.ts](src/lib.ts) — library entry (`Worker`, `runSession`,
  `posthogAiGatewayModel`). The harness imports from here.

## Rules of engagement

1. **No HTTP in this service.** The runner is queue-driven. If you
   reach for express or fetch-as-server, you're in the wrong place —
   it belongs in ingress (inbound) or janitor (authoring).

2. **Side effects go through injected interfaces.** The bundle store,
   queue, sandbox pool, secret broker, log sink, event bus are all
   constructor args on `Worker`. Don't import a concrete impl inside
   the loop — that breaks the harness's ability to substitute a faux
   sandbox / in-memory bus / in-process sink.

3. **Concurrency lives in `Worker`, not in the loop.** `driver.ts`
   runs one session at a time. If you find yourself adding `Promise.all`
   over sessions inside the driver, that's a layering mistake.

4. **Every loop branch publishes a lifecycle event.** `session_started`,
   `turn_started`, `tool_called`, `completed`, `waiting`, `failed`, etc.
   Silent paths defeat the SSE + Kafka log story.

## When you change something here

A change to the loop, the dispatcher, or any resolver needs an e2e
case in [services/agent-tests/](../../services/agent-tests/). The
harness drives a real `Worker` against the faux pi-ai provider — that's
the only place the integration actually runs end-to-end. See
[agent-tests/CLAUDE.md](../../services/agent-tests/CLAUDE.md).

Unit tests (`driver.test.ts`, `build-agent-tools.test.ts`) are fine for
pure shape (outcome derivation, tool-adapter behavior) — they don't
replace the e2e case.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md).
- **Prod env vars** —
  [docs/agent-platform/docs/deploy-runbook.md](../../docs/agent-platform/docs/deploy-runbook.md)
  (look for `agent-runner`).
- **Shared building blocks** —
  [services/agent-shared/](../agent-shared/) (queue, bundle, spec,
  sandbox, storage).
- **Django authoring side** —
  [products/agent_platform/CLAUDE.md](../../products/agent_platform/CLAUDE.md).
