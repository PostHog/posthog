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
  `PgRevisionStore`, `PgSandboxInstanceStore`, `PgApprovalStore`. SQL
  schema lives in [@posthog/agent-migrations](../agent-migrations/),
  not here.
- [src/storage/](src/storage/) — `BundleStore` interface +
  `FsBundleStore` impl.
- [src/sandbox/](src/sandbox/) — `SandboxImpl` interface +
  `InProcessSandboxPool` (the default; Modal lives elsewhere).
- [src/runtime/](src/runtime/) — `SessionEventBus` interface +
  `MemorySessionEventBus`, `LogSink` interface +
  `InMemoryLogSink`, `IdentityStore` + `MemoryIdentityStore`,
  `SecretBroker`.
- [src/memory/](src/memory/) — `MemoryStore` interface +
  `S3MemoryStore`. Markdown + YAML frontmatter file format;
  MiniSearch-backed BM25 over file bodies for the
  `@posthog/memory-search` tool. **Tests always run against real
  SeaweedFS/S3, never an in-process fake** — same philosophy as the
  real-PG tests; a fake just hides shape drift.

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

4. **Schema lives in `@posthog/agent-migrations`.** This package no
   longer carries inline SQL constants. New tables or columns go in a
   new migration file there. Test harness pulls `reset()` from the
   migrations package; production runs `bin/migrate --scope=agent_runtime`
   before service boot. **Never** ship a feature that runs `CREATE
TABLE IF NOT EXISTS` at runner / janitor / ingress boot — schema
   drift then becomes silent (column adds no-op) and prod tooling
   that depends on `pgmigrations` is bypassed.

5. **Cross-process services are constructor-injected, not module
   singletons.** Wire each impl at the entrypoint and pass it through
   `WorkerDeps` → `runSession` → dispatcher into `ToolContext` (see
   `memoryStore` for the worked example). Tests substitute an
   in-memory variant by constructing it directly; no `setX()` /
   `getX()` global. The pre-existing `posthog-client.ts` /
   `memory-broker.ts` (deleted) pattern is the antipattern we're
   moving away from.

6. **Prefer well-tested libraries over hand-rolled rankers /
   parsers.** MiniSearch (`@posthog/agent-shared`'s `search.ts`) is
   the precedent: a ~7KB dep that gives BM25 + field weighting + IDF
   without us having to get it right. The same logic applies to YAML,
   markdown, regex-glob, etc. — if it's load-bearing in prod, swap
   in the off-the-shelf option even when the hand-rolled version "works."

## Pointers

- **Local dev + MCP local + e2e overview** —
  [docs/agent-platform/docs/local-dev.md](../../docs/agent-platform/docs/local-dev.md).
- **Spec consumers** —
  [services/agent-janitor/src/validate-spec.ts](../agent-janitor/src/validate-spec.ts)
  (freeze-time check), [services/agent-runner/src/loop/](../agent-runner/src/loop/)
  (session-start check).
- **Test conventions** —
  [services/agent-tests/CLAUDE.md](../agent-tests/CLAUDE.md).
