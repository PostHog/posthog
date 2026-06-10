# agent-coder — example coding agent

A reference **coding-enabled** agent: its loop runs inside a tier-2 sandbox
(the real PostHog Code `agent-server` harness) where it has a shell,
filesystem, and real code execution — supervised from outside by the
platform. The companion to `agent-concierge`, but for the
`docs/agent-platform/plans/agent-sandbox-tiers.md` topology.

## What makes it a coding agent

`spec.json` carries the `sandbox` block:

```jsonc
"sandbox": {
  "trust_profile": "coding-write",   // provisions a tier-2 coding sandbox
  "loop_location": "in_sandbox",     // the LLM loop runs in the sandbox
  "workspace": { "ref": "local" }
}
```

Everything else (model, triggers, auth, limits) is an ordinary spec. The
`sandbox` field is optional and additive — agents without it keep today's
`frozen` behaviour.

## How it runs (local)

The platform supervisor (`services/agent-runner/src/loop/coding-supervisor.ts`,
`runCodingSession`) provisions the published harness image
(`ghcr.io/posthog/posthog-sandbox-base:master`) in Docker, mints the RS256
connection JWT, opens the harness's SSE `/events` session, relays the user
turn, and streams the ACP events back — with the model proxied through the
local ai-gateway.

End-to-end coverage lives in
`services/agent-runner/src/loop/coding-supervisor.realharness.test.ts`
(opt-in: needs Docker, the published image, and the local ai-gateway). It
drives this exact shape through the real harness to completion.

> Local-dev note: the dev ai-gateway omits `context_window` on `/v1/models`
> (the harness requires it) and routes only the bare model SKU
> (`claude-sonnet-4-6`). The e2e test injects `context_window` via a tiny
> in-process shim and sets the SKU accordingly. Both are local-gateway
> quirks, not platform issues — see the plan §11.
