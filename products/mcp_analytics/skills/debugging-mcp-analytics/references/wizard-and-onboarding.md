# Wizard install, skill distribution, and in-app onboarding

A customer counts as "onboarded" only once we have captured MCP events from their server. The
loop is: instrument (wizard) -> events flow -> analyze (dashboard or agent). This file covers
the install half and the in-app half.

Resolve `context-mill`, `wizard`, and `wizard-workbench` checkouts via
[local-repos.md](local-repos.md); they are internal repos and may be absent.

## `wizard mcp-analytics`

`npx -y @posthog/wizard@latest mcp-analytics` runs an agentic codemod that instruments a
user's _own_ MCP server, in TypeScript/JavaScript **or Python**. It is not `wizard mcp add`,
which installs the PostHog MCP server into a coding agent.

Two repos cooperate:

- **`context-mill`** holds the skill at `context/skills/mcp-analytics/`: `config.yaml` (with
  the `cli:` block that declares the command) and `description.md` (the codemod instructions
  themselves). `CONTRIBUTING.md` is the spec for skills and for the `cli:` block.
- **`wizard`** registers the command word: `src/commands/mcp-analytics.ts` calls
  `nativeCommandFactory(...)`, whose config lives in `src/lib/programs/mcp-analytics/index.ts`
  (built with `createSkillProgram`), wired in via `.use()` in `bin.ts`.

**Version source of truth in context-mill is its git tags**, not `package.json` — that field is
private and does not track releases.

## The rule for adding or changing a wizard command

The wizard is a thin Claude-Agent-SDK wrapper; capabilities come from context-mill skills
fetched at runtime via `skill-menu.json`. Which repos you touch depends on the shape:

- **A subcommand under an existing family** (e.g. another `wizard audit <thing>`) needs a
  **context-mill release only — no wizard PR.** It resolves at runtime from `cliEntries` by
  `parentCommand`, handled by `dispatch-family.ts` / `family-command-factory.ts`.
- **A brand-new top-level command** (which `mcp-analytics` is) **also needs a wizard PR**,
  because `bin.ts` statically `.use()`s every top-level command and yargs has no dynamic
  top-level registration. Ship both: the `cli:` block in context-mill, and a
  `nativeCommandFactory(ProgramConfig)` stub in the wizard
  (`src/lib/programs/<cmd>/index.ts` via `createSkillProgram`, plus `src/commands/<cmd>.ts`,
  plus `.use()` in `bin.ts`).

Model a new one on `migrate`, which is also a flat `createSkillProgram` call.
`revenue-analytics` uses the same factory but a fully hand-authored `ProgramConfig`, so it is a
weaker template. Keep a command flat until a second subcommand actually exists. The
`developing-the-wizard.mdx` handbook page in `posthog.com` documents this.

## The release gate

Nothing reaches users until a **context-mill release**: merge the skill PR with the
`mcp-publish` label plus one of `major` / `minor` / `patch`, and `build-release.yml` publishes
the GitHub release and moves the `latest` tag that the wizard pulls from. A change to the
command _word_ additionally needs a **wizard release** (release-please to npm). Order matters:
context-mill first, then wizard.

## Codemod instrumentation paths

Defined in the skill's `description.md`. Each detects a server shape and applies the matching
instrumentation:

| Path        | Target                                                        | Approach                                                                    |
| ----------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **A**       | official `@modelcontextprotocol/sdk` (`Server` / `McpServer`) | `instrument(server, posthog)`                                               |
| **B**       | `mcp-handler` (Vercel/Next)                                   | `instrument()` plus `identify` plus a per-invocation flush                  |
| **C**       | custom dispatcher (Hono/edge, no server object)               | `PostHogMCP` with `captureToolCall` / `captureInitialize`                   |
| **D**       | `@rekog/mcp-nest` (NestJS)                                    | `instrumentMutator()` through the framework's `serverMutator` hook          |
| **P1 / P2** | Python (`posthog.mcp`)                                        | official-SDK/FastMCP `instrument()`, or `PostHogMCP` for custom dispatchers |

Only path A has been verified against a real third-party server. B, C, D and the Python paths
are unverified — treat a report of them working as new information.

The codemod also handles credentials (the project token, fetched via the PostHog MCP
`posthog:projects-get` tool), lifecycle (shutdown and flush), STDIO-safe logging (stderr is fine,
stdout corrupts the protocol stream), and version pinning. The TypeScript paths **never hardcode
an SDK version** — they install the current published one and read the result back. The Python
paths are different: they require a floor (`posthog>=7.21`), which _can_ go stale, so check it
against the current `posthog` release when touching the Python instrumentation.

On failure it emits exactly one `[ABORT] <reason>` line and stops, from this vocabulary:

- `[ABORT] no mcp server found`
- `[ABORT] unsupported language for mcp analytics`
- `[ABORT] could not locate the server entry point`
- `[ABORT] <short specific reason>` (catch-all)

The wizard maps these reasons to friendlier messages in `MCP_ANALYTICS_ABORT_CASES`
(`src/lib/programs/mcp-analytics/index.ts`), matching each with an anchored regex against the
reason text after the `[ABORT]` prefix is stripped. Anything unmatched falls through to
generic handling.

**The two sides drift, so check both before trusting the mapping.** The table has carried a case
for `not a javascript mcp server` — a reason the codemod does not emit — while having none for
`could not locate the server entry point`, which it does. The result is dead copy that never
renders and a real abort that degrades to a generic message. If you add or rename a reason in
the codemod, update that table in the same change, and verify the regex against how the
consumer extracts the reason rather than assuming.

## Skill distribution — three channels

Do not confuse these; they have different audiences and different release mechanics.

1. **Team skills store** (Postgres) — reachable over MCP via `posthog:skill-list` / `posthog:skill-get`, and
   in-app under `/llm-analytics/skills/`. Per-team and editable without a deploy.
   `sync_canonical_skills` (`products/signals/backend/scout_harness/lazy_seed.py`) only
   promotes directories under `products/signals/skills/` matching `signals-scout-*` or listed
   in `_COMPANION_SKILL_DIRS`, so **no `mcp_analytics` skill is canonical through it**. The
   `signals-scout-mcp-tool-calls` scout qualifies purely by prefix.
2. **context-mill release** (`skills-mcp-resources.zip`) — the wizard/**install** skills,
   including the `mcp-analytics` codemod, served by `services/mcp`'s `ResourceCatalog`
   (`src/hono/resource-catalog.ts`) as MCP prompts and resources. This is **also the sole
   backend for `posthog-cli api skill list|install`** (`services/mcp/src/cli/skills.ts`).
3. **`posthog_ai` `build_skills`** — `products/posthog_ai/scripts/build_skills.py` scans
   `products/*/skills/` into `dist/skills.zip`, which `ci-agent-skills.yml` publishes as a
   GitHub release. This is the channel that carries the customer-facing **analysis** skills
   (`querying-posthog-data`, the `exploring-mcp-*` set, `improving-mcp-tools`) and this skill.
   Consumed by PostHog Desktop and PostHog AI. **Not** by `posthog-cli` — that is channel 2.

Two lookalikes are **not** MCP-analytics skills:
`products/managed_migrations/skills/testing-mcp-tools-locally/` and
`.agents/skills/implementing-mcp-tools/`. Both concern building and testing PostHog's own MCP
server tools, not analyzing MCP usage.

Note the activation gap: `wizard mcp add` installs the PostHog MCP server but does **not**
auto-load the analysis skills, so a freshly onboarded user has the data and the server without
the skills that read them.

## In-app onboarding

Two entry paths coexist, sharing one install hero.

1. **In-scene empty state — the current default.** MCP analytics is the reference adoption of
   the shared `ProductEmptyState` platform (`frontend/src/lib/components/ProductEmptyState/`).
   A scene's `SceneExport` declares `emptyState`; `productSetupStatusLogic` exposes a
   normalized `ProductSetupStatus` (`loading`, `needs-setup`, `waiting-for-data`, `has-data`).
   MCP's config is `products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState.tsx`,
   mapped from the product's own onboarding state by
   `emptyStateStatusForOnboardingState()`. **Projects that have never been set up render the
   setup screen in place — there is no redirect into the app-wide `/onboarding` flow.**
   `manifest.tsx` declares the `setupProbe` (`hasDataEvents: ['$mcp_tool_call']`,
   `waitingEvents: ['$mcp_initialize']`). That `waitingEvents` probe never resolves for a
   stateless-only server, which emits no `$mcp_initialize`: such a project reads as
   `needs-setup` until its first tool call and then goes straight to `has-data`, skipping
   `waiting-for-data`. See [stateless-and-sessions.md](stateless-and-sessions.md).
2. **The legacy app-wide `/onboarding` flow** is still registered, under
   `frontend/src/scenes/onboarding/legacy/stepProviderRegistry.ts` — the `legacy/` segment
   signals it is being phased out. Registering a product there takes roughly six touches:
   `ProductKey.MCP_ANALYTICS` (`schema-general.ts`), `Scene.MCPAnalytics` (`sceneTypes.ts`),
   the `AvailableOnboardingProducts` union (`types.ts`), an `availableOnboardingProducts` entry
   (`onboarding/shared/utils.tsx`), the provider in `legacy/stepProviderRegistry.ts`, and the
   custom install step (`products/mcp_analytics/frontend/onboarding/steps.tsx`).

**They do not share a component — check which one you're editing.** Only the legacy path renders
`MCPAnalyticsInstallHero` (`frontend/onboarding/MCPAnalyticsInstall.tsx`, imported by
`onboarding/steps.tsx`). The default in-scene path is `emptyState/mcpAnalyticsEmptyState.tsx`,
which imports just `MCP_ANALYTICS_DOCS_URL` and `MCPListeningIndicator` from that file and
otherwise renders through the shared `ProductEmptyState`. Editing the hero therefore does _not_
change the setup screen most users see.

Both surfaces do use `useWizardCommand('mcp-analytics', { pinProjectId: true })` — `pinProjectId`
appends `--project-id=<team>` so the wizard instruments the project the user is looking at —
together with the rainbow `CommandBlock`, deliberately bypassing the shared
`WizardCommandBlock` for **bundle weight**, since the empty-state gate is eagerly loaded.
(`WizardCommandBlock` does support a `subcommand` prop, so "it can't express a subcommand" is
no longer the reason.)

`mcpAnalyticsOnboardingLogic` drives all of it with a single **unbounded** HogQL query
(`ONBOARDING_SIGNAL_QUERY`, effectively "has this project ever been onboarded" — cheap,
because the event-name filter hits the sort key) returning `has_initialize`,
`tool_calls_total`, `tool_calls_7d`, and `first_call_at`, polled on an interval and torn down
through `cache.disposables`. States are `not-instrumented`, `connected-no-calls`, and
`onboarded`; it also derives the `dashboardStage` that gates the landing tab. Product-intent
reporting is suppressed during staff impersonation via `isImpersonatedSession()`.

Not yet adopted: the generic wizard **setup-report handoff** (`publish_handoff` ->
`handoff_text` -> `WizardHandoffDialog`). The `mcp-analytics` program gets the publishing side
automatically, as any `createSkillProgram` program with a report file does, but no
MCP-analytics surface consumes the report yet.

## Testing the install flow locally

`wizard-workbench` drives the real command against fixture apps. Run its setup script (see the
repo's README), which brings up the local stack, then run `wizard mcp-analytics` against the
fixtures in `apps/mcp-analytics/`: `typescript-sdk/stdio-server/` exercises path A and
`custom-dispatcher/hono-server/` exercises path C. **There are still no Python fixtures**, so
the Python paths cannot be exercised here yet.

By default the wizard pulls skills from the latest context-mill _release_; the `--local-mcp`
flag serves the unreleased local skill instead, which is what you want when testing a codemod
change before publishing it.

Two things that cost people time:

- Workbench **CI** no longer runs a local MCP server at all — it points `MCP_URL` at the
  production MCP endpoint to decouple CI from monorepo breakage. So a CI green does not prove
  the local-stack path works, and vice versa.
- The local `mcp` process is not started automatically by the process manager even though older
  README text implies it is; start it explicitly if something expects it to be listening.
