# agent-shared — Shared building blocks for the v2 agent platform

Library, not a deployable service. Everything the three node services
(ingress, runner, janitor) share lives here: persistence, spec schema,
sandbox interface, bundle store, runtime types.

Read [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md)
for the wider dev flow.

## What lives here

- [src/spec/](src/spec/) — `AgentSpecSchema` (zod). **The source of
  truth** for the `revision.spec` JSONB shape. The Django side
  validates loosely and passes through; this schema is authoritative.
- [src/persistence/](src/persistence/) — `PgSessionQueue`,
  `PgRevisionStore`, `PgSandboxInstanceStore`, the `SCHEMA_SQL` /
  `AUTHORING_SCHEMA_SQL` constants.
- [src/storage/](src/storage/) — `BundleStore` interface +
  `FsBundleStore` impl.
- [src/sandbox/](src/sandbox/) — `SandboxImpl` interface +
  `InProcessSandboxPool` (the default; Modal lives elsewhere).
- [src/runtime/](src/runtime/) — `SessionEventBus` interface +
  `MemorySessionEventBus`, `LogSink` interface +
  `InMemoryLogSink`, `IdentityStore` + `MemoryIdentityStore`,
  `SecretBroker`.

## Rules of engagement

1. **No HTTP, no process boundaries, no bin entry.** This is a
   library. If you're tempted to add `express` or `startServer`,
   you're in the wrong package.

2. **Interfaces first, then impls.** Every cross-process boundary
   (queue, bundle, sandbox, bus, log sink, identity, secret) is an
   interface here. Concrete impls (in-memory, Pg, FS, Redis, Kafka)
   are sibling files. The harness substitutes in-memory variants —
   keep that swap cheap.

3. **`AgentSpecSchema` is the contract — change it carefully.**
   Tightening a field can reject revisions Django happily wrote.
   Loosening can let the runner accept specs that downstream code
   can't handle. Mirror janitor `validate-spec.ts` whenever you
   touch this.

4. **Schema SQL changes are migrations.** `SCHEMA_SQL` is dropped +
   recreated per harness test, but in prod it bootstraps a fresh DB
   only on first boot. Real schema changes need an entry in the
   migration scope (`bin/migrate --scope=agent_runtime`), not just
   an edit to the constant.

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md).
- **Spec consumers** —
  [services/agent-janitor/src/validate-spec.ts](../agent-janitor/src/validate-spec.ts)
  (freeze-time check), [services/agent-runner/src/loop/](../agent-runner/src/loop/)
  (session-start check).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
