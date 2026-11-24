# MCP development guide

## Commands

Run these commands from the repository root:

- Run `pnpm --filter=@posthog/mcp run typecheck` after changing TypeScript or TSX files. It checks types without emitting files.
- Run `pnpm --filter=@posthog/mcp run format` to apply Oxfmt only. Use `lint` and `format:check` for verification; neither command rewrites files.
- Run `pnpm --filter=@posthog/mcp run lint:fix` to apply safe Oxlint fixes. It does not apply suggestion fixes that may change behavior.
- Run `pnpm --filter=@posthog/mcp run fix` before committing JavaScript, TypeScript, JSON, YAML, CSS, or SCSS changes. It applies safe Oxlint fixes, always runs Oxfmt, and fails if either tool fails.

## Product-specific agent text

- **Text about one product lives in that product's files.** `[review]` Put a workflow in a skill under `products/<name>/skills/`. Put a note on a tool's result in `agent_note` in the product's `tools.yaml`. Every product shares `src/tools/exec.ts` and `src/templates/sections/`, so keep product text out of them.
- A redirect for a removed tool is the exception. It goes in `DEPRECATED_TOOL_REDIRECTS` in `src/tools/exec.ts`.

## Shared core: ask team-context-and-mcp first

The core is the code and text that every customer's agent hits:
`src/tools/exec.ts`, `src/tools/exec-learn.ts`, `src/hono/instructions.ts`, `src/lib/instructions-formatter.ts`, `src/hono/guidance/`,
and the `cli-*`, `exec-*`, `basic-functionality`, `compact-instructions`, `skills-first` and `tool-search` sections in `src/templates/sections/`.

- **A change to a core file from outside `team-context-and-mcp` is agreed with the team before you write it.** `[review]` Before you edit a core file, stop and tell the user which file the change touches and why. Then ask them to agree the change in `#team-context-and-mcp`, or to tell you explicitly to continue without it. Do not ask when the user says they are on the team.
- Stamphog does not approve a core change from an author outside the team, so a human must approve it. Request [`PostHog/team-context-and-mcp`](https://github.com/orgs/PostHog/teams/team-context-and-mcp) as reviewers.
- In the PR description, include a short **MCP core** note. Say what changes for every agent, and who agreed it, or that the author continued without agreement.

## Unsolicited elicitation

Unsolicited elicitation interrupts an agent mid-task and puts a question in front of the user.
Used carelessly, it becomes spam and damages trust in the MCP.

- Interview recruitment is the existing path for research invitations. Read the [interview recruitment guide](INTERVIEW_RECRUITMENT.md) before you add a study or change the flow. It documents the capability checks, exclusions, warmup, suppression, and analytics.
- Check in with the MCP team before you add a new kind of unsolicited prompt (surveys, upsells, promotional questions), or before you widen reach or frequency or weaken suppression or opt-out behavior. `[review]`

Elicitation that the user's requested task needs, such as a clarification or confirmation, is a separate use case.

## MCP Analytics

- Before adding or changing MCP Analytics instrumentation, read the [tracking and observability architecture](ARCHITECTURE.md#tracking-and-observability).
- Prefer `@posthog/mcp-analytics` for all MCP telemetry it supports. The SDK should own reusable MCP Analytics behavior. Server code should only provide the relevant typed data and PostHog-specific integration.
- Do not duplicate SDK behavior with custom event capture, property mapping, session handling, identity handling, or other parallel instrumentation.
- Event and property names beginning with `$mcp_` are owned by MCP Analytics SDKs. Do not invent, add, rename, reinterpret, or manually populate `$mcp_*` fields in server code unless the SDK explicitly exposes them for that purpose.
- Before introducing a new MCP Analytics event, property, or concept, check whether the SDK already supports it or whether it belongs in the SDK.
- If the SDK does not support a required signal or event, discuss the design with `@team-mcp-analytics` in Slack (`#team-mcp-analytics`) before implementing it. Prefer extending the SDK when the signal could be useful to other MCP Analytics customers. A custom event can be more appropriate for a product-specific or one-off need, but sync with the team first.
- Assign [`PostHog/mcp-analytics`](https://github.com/orgs/PostHog/teams/mcp-analytics) as a reviewer on every PR that changes MCP Analytics instrumentation.
- In the PR description, include a short **MCP Analytics** note that summarizes the changed analytics behavior, why it is needed, and whether it uses existing SDK support or requires something new.
