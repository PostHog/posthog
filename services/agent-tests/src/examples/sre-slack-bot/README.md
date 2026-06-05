# SRE Slack bot — alert triage assistant

First-iteration ("infant") SRE assistant.
Fires on Grafana alertmanager webhook calls and on `@mentions` from
Slack, gathers context using PostHog data + runbook URLs + Slack
thread history, posts a structured triage report back in the thread,
and ends the session.

## Status

**Infant.** Buildable today on shipped primitives — no platform
work blocks it.
Several value-loops are duct-taped because the proper primitive
doesn't exist yet; see [Gaps](#gaps-that-constrain-the-infant-version) below.

## What it does

| Capability                                | How                                                                                      |
| ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| Triggered by Grafana alerts               | `webhook` trigger at `/agents/<slug>/webhook` (request body is the alertmanager payload) |
| Triggered by Slack `@mention`             | `slack` trigger, `mention_only: true`                                                    |
| Chattable from the agent console          | `chat` trigger — open the agent in the console and use the playground dock               |
| Calls the Slack Web API directly          | `@posthog/http-request` + `SLACK_BOT_TOKEN` secret (bring-your-own bot, no integration)  |
| Queries PostHog event data + logs         | `@posthog/query`                                                                         |
| Fetches runbook URLs                      | `@posthog/web-fetch`                                                                     |
| Remembers prior incident outcomes         | `@posthog/table-query`, `@posthog/table-append` on the `incidents` table                 |
| Follows a structured triage flow          | `skills/triage-playbook/SKILL.md`                                                        |
| Follows a consistent Slack message format | `skills/slack-thread-protocol/SKILL.md`                                                  |

## What it cannot do

- Take **any** remediation action. No restarts, no scaling, no
  rollbacks. Output is information only.
- Query Grafana dashboards or run `kubectl` directly. Asks a human
  for screenshots / `kubectl` output when needed.
- Page anyone. Surfaces who to `cc` and lets a human decide.

## Bundle layout

```text
sre-slack-bot/
├── README.md                            # this file
├── spec.json                            # AgentSpec — triggers, tools, skills, limits
├── agent.md                             # system prompt
└── skills/
    ├── triage-playbook/SKILL.md         # how to investigate
    └── slack-thread-protocol/SKILL.md   # how to reply in Slack
```

## Prerequisites for deploying

1. **Your own Slack app** registered at api.slack.com — see "Slack
   setup" below. The bot calls Slack's Web API directly with the
   `xoxb-…` token you generate, which lives in `spec.secrets` as
   `SLACK_BOT_TOKEN`. No platform-managed Slack integration is needed.
2. **`spec.triggers[].slack.trusted_workspaces`** updated from the
   placeholder `T0XXXXXXX` to your actual Slack team id.
3. **Grafana alertmanager** configured to POST alert payloads to
   `https://<ingress-host>/agents/<slug>/webhook`. The webhook
   trigger currently has no shared secret set in
   `spec.triggers[].webhook.config.secret` — add one before
   exposing publicly. (`config.path` is metadata only today;
   per-path routing is a future expansion.)
4. **PostHog API access** for `@posthog/query` — the standard
   team-level token, no special scopes.

### A note on auth

`spec.auth.mode` is `public` because the running ingress
([`services/agent-ingress/src/index.ts`](../../../../agent-ingress/src/index.ts))
doesn't wire an `AuthProvider` — `pat`, `shared_secret`, and
`posthog_internal` modes all 401 against an unwired ingress.
Before exposing this agent on the internet, wire a real auth
provider _and_ change `auth.mode` to match.

## Deploying

Through the authoring MCP (preferred):

```text
# In an MCP-aware client (Claude Desktop, Claude Code, MCP Inspector):
agent-applications-create slug=sre-slack-bot name="SRE triage bot"
agent-applications-revisions-create application_id=<id>
# upload bundle files via agent-applications-revisions-bundle-put
agent-applications-revisions-spec-patch revision_id=<rid> spec=<contents of spec.json>
agent-applications-revisions-freeze revision_id=<rid>
agent-applications-revisions-promote revision_id=<rid>
```

See [`docs/agent-platform/docs/local-dev.md`](../../../../../docs/agent-platform/docs/local-dev.md)
§"Local MCP — end-to-end via an MCP client" for the full flow.

Directly via the janitor's REST API:

```bash
# Substitute <janitor-url>, <application-id>, etc.
curl -X POST <janitor-url>/revisions \
  -H 'x-internal-secret: <secret>' \
  -d '{ "application_id": "<id>", "spec": <contents of spec.json> }'
# then bundle-put per file, freeze, promote.
```

## Regression test

[`services/agent-tests/src/cases/example-sre-bot.test.ts`](../../cases/example-sre-bot.test.ts)
loads this bundle from disk, deploys it through the e2e harness,
and drives a realistic alert flow with the faux model. Run with:

```bash
pnpm --filter @posthog/agent-tests test cases/example-sre-bot
```

## Gaps that constrain the infant version

These come from
[`docs/agent-platform/plans/_APP_IDEAS.md`](../../../../../docs/agent-platform/plans/_APP_IDEAS.md).
Each one is a follow-up that would make the bot meaningfully more
useful:

- **Private-network MCP support (Grafana / k8s).** Public MCPs work
  today via the `kind: 'external'` McpRef
  ([`runtime-mcps.md`](../../../../../docs/agent-platform/plans/runtime-mcps.md));
  Grafana and Kubernetes typically aren't publicly reachable.
  Cloudflare Tunnel is the planned v1 path; `kind: 'tailscale'`
  is parked
  ([`tailscale-mcps.md`](../../../../../docs/agent-platform/plans/tailscale-mcps.md)).
- **Runbook corpus retrieval** — `@posthog/web-fetch` works for a
  single URL but the bot needs an index over the whole runbook
  tree. Could mirror periodically into the `memory-*` store via a
  loader job; not yet built.

## Tuning notes

- The system prompt is intentionally opinionated about formatting
  (`slack-thread-protocol.md`) — channel signal-to-noise matters
  more than terseness. Adjust per team taste.
- `reasoning: high` is set because the triage step benefits from
  long deliberation. If you're cost-sensitive, drop to `medium`
  and re-evaluate against real traffic.
- `limits.max_turns: 30` is generous; most healthy investigations
  finish in 5-10 turns. The higher cap protects against pathological
  loops (each turn still counts against `max_tool_calls` and
  `max_wall_seconds`).
