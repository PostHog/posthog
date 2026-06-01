# Agent concierge — the meta-agent for the platform

The "explain, debug, edit" assistant for every agent on the
PostHog agent platform. One deployment, three surfaces (agent
console chat dock, MCP from Claude Code / Cursor, future Slack),
all acting under the user's PostHog OAuth principal.

## Status

**Reference bundle.** Loadable + faux-testable today. Production
deployment is gated on platform pieces tracked in
[`docs/agent-platform/plans/agent-concierge.md`](../../../../../docs/agent-platform/plans/agent-concierge.md)
§8 — client-fulfilled tools, runtime MCPs, OAuth principal
threading, the validate / test-run / secrets-punch-out MCP verbs.

The bundle itself doesn't need any of those to load and parse;
the gaps only matter at runtime when the agent actually tries to
call the tools.

## What it does

| Mode    | Trigger                                                     | Primary skill             |
| ------- | ----------------------------------------------------------- | ------------------------- |
| Inspect | "what does X do?" / "is X healthy?" / "show me Y"           | `reading-an-agent`        |
| Debug   | "why did session Y fail?" / "X is broken" / "X did Z wrong" | `debugging-sessions`      |
| Edit    | "change X" / "tweak the prompt" / "add a tool"              | `editing-agents-safely`   |
| Author  | "build me a new agent that..."                              | `authoring-new-agents`    |
| Audit   | "audit my team's agents" / "where's our cost going?"        | `cost-and-quota-analysis` |

For each mode, the concierge calls the same `agent-applications-*`
MCP tools that the authoring AI uses (`docs/agent-platform/plans/agent-authoring-flow.md`),
acting under the connected user's principal so every write shows
up in the activity log as **the user**, not as the concierge.

## Bundle layout

```text
agent-concierge/
├── README.md                            # this file
├── spec.json                            # triggers, tools, mcps, skills
├── agent.md                             # short system prompt; defers to skills
└── skills/
    ├── platform-mental-model.md         # spec / bundle / revision / session
    ├── reading-an-agent.md              # standard inspection flow
    ├── debugging-sessions.md            # failure taxonomy + triage
    ├── editing-agents-safely.md         # branch → validate → freeze → test → promote
    ├── authoring-new-agents.md          # fresh creation flow
    ├── secrets-and-integrations.md      # punch-out flow, integrations table
    ├── designing-mcp-surfaces.md        # spec.mcp.tools[] design
    ├── running-and-evaluating-tests.md  # tests + judge skills
    ├── using-the-console-ui.md          # focus_* + toast etiquette
    ├── working-outside-the-console.md   # MCP / IDE mode; no client tools
    ├── cost-and-quota-analysis.md       # LLM analytics views
    └── safety-and-boundaries.md         # hard rules
```

## Tool surface

| Class  | Tool                                                                                                       | Class semantics                                                                                                                                                                        |
| ------ | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native | `@posthog/agent-applications-*` (list, retrieve, revisions, sessions, logs)                                | Read agent state — applications, revisions, sessions, logs — as the connected user. Routed through the credential broker; no platform credentials, no impersonation. Read-only for v0. |
| Client | `focus_tab`, `focus_file`, `focus_revision`, `focus_session`, `focus_spec_section`, `toast`, `get_context` | Drive the console's read panel + read the user's current view. No-op outside the console.                                                                                              |

## Auth model

The bundle uses `spec.auth.mode: posthog_internal`. Both entry
points map to the same effective auth:

1. **Console** — user logs into `console.agents.posthog.com` via
   PostHog OAuth, the console mints a short-lived session-principal
   token from the OAuth session, attaches it as the chat trigger's
   principal field. Every tool call runs as the user.
2. **MCP** — user attaches their PostHog PAT in their MCP client
   config. The runner resolves the PAT to a principal once at
   session start, threads it through identically.

The concierge holds no fallback credential.

## Prerequisites for production deployment

These are platform-side, not bundle-side:

1. **`kind: "client"` tool support in the spec** —
   `docs/agent-platform/plans/agent-console-website.md` §8. Today
   the spec parser doesn't accept `kind: "client"`; the bundle's
   `focus_*` and `toast` entries will fail
   validation at load.
2. **Runtime MCP support** — `docs/agent-platform/plans/runtime-mcps.md`.
   Today the runner reads `spec.mcps[]` but doesn't open clients.
   The concierge would silently lose every `posthog__*` tool call.
3. **OAuth principal threading** —
   `docs/agent-platform/plans/per-session-access-elevation.md` +
   `docs/agent-platform/plans/agent-console-website.md` §7.1.
   Without it, the concierge couldn't act as the user.
4. **The MCP verbs the concierge calls** —
   `agent-applications-*` are scaffolded in
   [`services/mcp/definitions/agent_stack.yaml`](../../../../mcp/definitions/agent_stack.yaml).
   `validate-create` is `enabled: true` but the underlying action
   is a stub; `test-run` / `secrets-issue-write-token` / `diff`
   aren't there yet.

See the plan for the full gap list + phasing.

## Deploying once gaps land

Through the authoring MCP (preferred — same as other example bundles):

```text
agent-applications-create slug=agent-concierge name="Agent concierge"
agent-applications-revisions-create application_id=<id>
# upload all bundle files via agent-applications-revisions-bundle-update
agent-applications-revisions-partial-update revision_id=<rid> spec=<contents of spec.json>
agent-applications-revisions-validate-create revision_id=<rid>
agent-applications-revisions-freeze-create revision_id=<rid>
agent-applications-revisions-promote-create revision_id=<rid>
```

The concierge lives in **PostHog's primary org** so it's
available to every team via the standard MCP / chat ingress. The
spec's `auth.mode: posthog_internal` means it's not callable as
a random external bot — only the console's signed session-
principal token + verified user PATs get through.

## Regression test

[`services/agent-tests/src/cases/example-agent-concierge.test.ts`](../../cases/example-agent-concierge.test.ts)
loads the bundle from disk and asserts:

- `spec.json` parses against `AgentSpecSchema`
- Every `spec.skills[].path` exists in the bundle
- `agent.md` is present
- The MCP routes the concierge declares in `spec.mcps[].tools`
  all match the catalog in
  [`services/mcp/definitions/agent_stack.yaml`](../../../../mcp/definitions/agent_stack.yaml)

NOT a real-inference test — the model is faux. This is the wiring
regression net, not a quality bar. (When the platform gaps in
§8 of the plan close, add a real-inference case that drives a
realistic inspect / debug flow with mocked authoring MCP
responses.)

Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-agent-concierge
```

## Extending the concierge

Two ways:

1. **Fork.** Clone the bundle, edit, deploy under a different
   slug. Useful for teams that want bespoke review steps,
   internal links, or a different tone.
2. **Add a skill upstream.** New shared workflow (e.g.
   `judge-test-results`) → add a skill file + a
   `spec.skills[]` entry + a one-line description. Re-freeze.

Don't fork to add a tool that should be universally available —
add it to the canonical bundle so every team benefits.

## Tuning notes

- `reasoning: high` is set because debugging and editing benefit
  from long deliberation. Cost-sensitive deployments can drop to
  `medium` and re-evaluate.
- `limits.max_turns: 80` is generous; most flows finish in 5-15
  turns. The cap protects against pathological loops while
  allowing complex multi-step audits.
- The skill descriptions in `spec.skills[]` are deliberately
  prescriptive ("Load when..." / "Load IMMEDIATELY if...") —
  this is the only signal the model gets about when to fetch
  the skill body. Tune the descriptions before the bodies.
- `agent.md` is intentionally short. Anything beyond identity,
  mode-selection, hard rules, and tone belongs in a skill.
