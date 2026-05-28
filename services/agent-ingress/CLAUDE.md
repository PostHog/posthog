# agent-ingress — Inbound HTTP for the v2 agent platform

Owns every external entry point into a running agent: chat (`/run`,
`/send`, `/listen`), webhook (`/webhook`), Slack (`/slack/events`),
MCP (`/mcp`), domain + path routing, auth, identity.

Read [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md)
for the wider dev flow before non-trivial changes.

## What lives here

- [src/triggers/](src/triggers/) — one module per trigger type. Each
  resolves the principal, normalizes the input, enqueues a session.
- [src/routing/](src/routing/) — slug + domain resolution against the
  application table.
- [src/enqueue/](src/enqueue/) — the path from "validated request"
  → row in `agent_sessions`.
- [src/index.ts](src/index.ts) — prod bin entry. Reads env, wires
  real PG pools + `RedisSessionEventBus`, starts the listener.
- [src/lib.ts](src/lib.ts) — library entry (`buildApp`, the auth and
  event-bus types). The harness imports from here.

## Rules of engagement

1. **Ingress writes only to `agent_sessions` (+ `agent_user`).** It
   never touches `agent_application` / `agent_revision` except to
   read for routing. Authoring writes go through Django →
   janitor — not through here.

2. **Trigger handlers are skinny.** Verify signature → look up app →
   resolve identity → enqueue → return. Anything heavier is a smell —
   long work belongs in the runner, not in the request thread.

3. **`/listen` SSE depends on the bus.** The default
   `MemorySessionEventBus` only fans out within one process. Multi-host
   needs `REDIS_URL` (publishes via `RedisSessionEventBus`). If you
   add a new lifecycle event, make sure both bus impls carry it.

4. **Auth lives in `AuthProvider`, not inlined.** Don't bake principal
   lookup into a trigger handler — extend or swap the `AuthProvider`
   passed to `buildApp`.

## When you change something here

Trigger surface and routing edges have e2e cases under
[services/agent-tests/src/cases/](../../services/agent-tests/src/cases/)
(`chat-trigger`, `slack-trigger`, `webhook-mcp-trigger`,
`routing-edges`, `listen-sse`, `strict-principal`, ...). A change
without a matching case will regress silently.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md).
- **Prod env vars** —
  [docs/agent-platform/docs/deploy-runbook.md](../../docs/agent-platform/docs/deploy-runbook.md)
  (look for `agent-ingress`).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
- **Shared building blocks (queue, identity store, event bus types)** —
  [services/agent-shared/](../agent-shared/).
