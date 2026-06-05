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
  → row in `agent_session`.
- [src/index.ts](src/index.ts) — prod bin entry. Reads env, wires
  real PG pools + `RedisSessionEventBus`, starts the listener.
- [src/lib.ts](src/lib.ts) — library entry (`buildApp`, the auth and
  event-bus types). The harness imports from here.

## Rules of engagement

1. **Ingress writes only to `agent_session` (+ `agent_user`).** It
   never touches `agent_application` / `agent_revision` except to
   read for routing. Authoring writes go through Django →
   janitor — not through here.

2. **Trigger handlers are skinny.** Look up app → resolve secrets →
   verify signature → resolve identity → enqueue → return. Anything
   heavier is a smell — long work belongs in the runner, not in the
   request thread. (Slack flipped the app-vs-signature order: we resolve
   the agent first so we know which signing secret to use.)

   **Slack signing secret is per-agent, not global.** There is no
   `SLACK_SIGNING_SECRET` env. The Slack handler looks up the
   conventional `SLACK_SIGNING_SECRET_KEY` (from
   `@posthog/agent-shared`'s `TRIGGER_REQUIRED_SECRETS` registry) in the
   agent's `AgentApplication.encrypted_env` via
   `SlackSigningSecretResolver`, which decrypts on every request using
   the same `EncryptedFields` helper as everywhere else. Django's
   promote action gates on the entry being present so production
   requests always find a value. BYO Slack apps work day-1. To add
   another "trigger needs a secret in encrypted_env" use case, add an
   entry to `TRIGGER_REQUIRED_SECRETS` and look it up via the resolver
   — don't add a new global env var, and don't put the key name on the
   spec.

3. **`/listen` SSE depends on the bus.** The default
   `MemorySessionEventBus` only fans out within one process. Multi-host
   needs `REDIS_URL` (publishes via `RedisSessionEventBus`). If you
   add a new lifecycle event, make sure both bus impls carry it.

4. **Auth lives in `AuthProvider`, not inlined.** Don't bake principal
   lookup into a trigger handler — extend or swap the `AuthProvider`
   passed to `buildApp`.

5. **No `process.env` reads + one HttpClient.** Env access goes
   through `loadAgentIngressConfig` at boot; the typed `Config` flows
   from there. Every outbound HTTP call (PostHog API introspect,
   Slack identity bridge) reaches the wire via the shared `HttpClient`
   wired in `src/index.ts`. See agent-shared/CLAUDE.md rules 7-8 for
   the full story + the lint rule that enforces it.

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
