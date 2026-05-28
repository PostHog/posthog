# agent-runner — Worker loop for the v2 agent platform

The session executor. Claims from the queue, loads revision + bundle,
calls pi-ai, dispatches tools, persists conversation, publishes
lifecycle events.

You will almost always need the broader platform in your head — read
[docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md)
first.

## What lives here

- [src/loop/](src/loop/) — the per-turn execution: `run-turn.ts`,
  `dispatch-one.ts`, `tool-dispatch.ts`, `system-prompt.ts`,
  `build-tool-list.ts`.
- [src/workers/](src/workers/) — the outer `Worker` (claim → runOne →
  loop), concurrency, shutdown.
- [src/resolvers/](src/resolvers/) — secrets, integrations, model
  selection. Each is a function the caller can override; the harness
  - prod wire different concrete impls.
- [src/models/](src/models/) — `PiAiClient` + the LLM-gateway model
  factory.
- [src/index.ts](src/index.ts) — prod bin entry. Reads env, wires
  real PG pools + KafkaLogSink + RedisSessionEventBus, starts the loop.
- [src/lib.ts](src/lib.ts) — library entry (`Worker`, `PiAiClient`,
  `posthogLlmGatewayModel`). The harness imports from here.

## Rules of engagement

1. **No HTTP in this service.** The runner is queue-driven. If you
   reach for express or fetch-as-server, you're in the wrong place —
   it belongs in ingress (inbound) or janitor (authoring).

2. **Side effects go through injected interfaces.** The bundle store,
   queue, sandbox pool, secret broker, log sink, event bus are all
   constructor args on `Worker`. Don't import a concrete impl inside
   the loop — that breaks the harness's ability to substitute a faux
   sandbox / in-memory bus / in-process sink.

3. **Concurrency lives in `Worker`, not in the turn.** `run-turn.ts`
   handles one turn for one session at a time. If you find yourself
   adding `Promise.all` over sessions inside the turn, that's a
   layering mistake.

4. **Every loop branch publishes a lifecycle event.** `session_started`,
   `turn_started`, `tool_called`, `completed`, `waiting`, `failed`, etc.
   Silent paths defeat the SSE + Kafka log story.

## When you change something here

A change to the loop, the dispatcher, or any resolver needs an e2e
case in [services/agent-tests/](../../services/agent-tests/). The
harness drives a real `Worker` against the faux pi-ai provider — that's
the only place the integration actually runs end-to-end. See
[agent-tests/CLAUDE.md](../../services/agent-tests/CLAUDE.md).

Per-turn unit tests (`run-turn.test.ts`, `tool-dispatch.test.ts`,
`system-prompt.test.ts`) are fine for pure shape — they don't replace
the e2e case.

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
  [products/agent_stack/CLAUDE.md](../../products/agent_stack/CLAUDE.md).
