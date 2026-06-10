# Skill — debugging sessions

How to diagnose a failing or anomalous session — taxonomy of
failures, where to look for each, and what to surface to the user.

## First — establish what 'failing' means

The user might say "broken" when they mean any of:

- The session state ended in `failed`
- The session ended in `completed` but the output was wrong
- The session ran longer / cost more than expected
- The session asked for human approval and the approval timed out
- The session hung (`running` for too long, or `queued` and never
  picked up)

Ask one clarifying question if it isn't obvious from the trigger.
Then pick the matching branch below.

## The standard debug flow

1. **Pre-focus the session** if you have `@posthog/ui/focus`:
   `{ kind: 'session', session_id: <id> }`.

2. **Retrieve the session**.
   `@posthog/agent-applications-sessions-retrieve` returns the conversation,
   the principal, the state, started_at, ended_at, usage_total,
   trigger metadata.

3. **Retrieve the logs**.
   `@posthog/agent-applications-session-logs` returns the structured event
   stream — assistant turns, tool calls, tool results, errors,
   state transitions.

4. **Identify the failure class** from the taxonomy below.

5. **For each non-trivial failure** pull the revision (so you can
   reason about the agent's design, not just the symptom) — same
   calls as `skills/reading-an-agent` step 2 + 4.

6. **Produce a structured report** — see the report shape at the
   bottom.

## Failure taxonomy

The failure modes that account for almost every broken session.
For each: how to recognize it, where the evidence lives, what to
suggest.

### A. Provider error / network failure

**Recognize:** event log has a `provider_error` or
`gateway_error` event near the end. Session state usually
`failed`. Usage may be partial.

**Evidence:** the error event carries `error.type` and
`error.message`. Common ones:

- `gateway_error: model_overloaded` — provider rate limit. Retry
  generally works; the platform doesn't auto-retry mid-session.
  Suggest: re-run.
- `gateway_error: context_length_exceeded` — the conversation grew
  past the model's context window. Suggest: shorter skills, or
  enable `spec.resume` with a tighter compaction policy.
- `provider_error: invalid_api_key` — the LLM gateway / provider
  key is wrong. Surface to the user; they need an admin to fix.

**Action:** report the error verbatim + the immediate cause + the
fix. Don't speculate; provider errors are deterministic.

### B. Limit hit (`max_turns` / `max_tool_calls` / `max_wall_seconds`)

**Recognize:** session state `failed` with `failure_reason:
limit_exceeded`. Event log ends with an `error` event citing the
specific limit.

**Evidence:** the spec's `limits` block vs the session's
`turn_count` / `tool_call_count` / `wall_seconds`. Look at the
last 3-5 turns to see what the agent was doing when it ran out.

Common pattern: agent loops between two tools without making
progress (e.g. `read` then `read again`). That's a prompt issue,
not a limit issue — raising the limit would just delay the loop.

**Action:** classify the loop. If real progress was happening,
suggest raising the limit (and quote the new number). If a loop,
read the relevant skill / agent.md and suggest the prompt change
that breaks it.

### C. Tool error

**Recognize:** `tool_result` event with `is_error: true`. The
agent's next turn usually acknowledges or retries.

**Evidence:** the `tool_result.content` field carries the error
payload. Classify the source:

- **Native tool error** — e.g. `@posthog/slack-post-message`
  returns a Slack API 403. The runner faithfully relays the
  provider's error. Fix is usually integration / permission, not
  the agent.
- **MCP tool error** — `gateway_unavailable`, `tool_not_found`,
  or the remote MCP server returned an error. Check whether the
  MCP endpoint in `spec.mcps[]` is up (the runner doesn't health-
  check it; you may need to `@posthog/agent-applications-sessions-list`
  for other agents using the same MCP to confirm cross-impact).
- **Custom tool error** — the sandboxed code threw or the
  sandbox killed it (`sandbox_oom`, `sandbox_timeout`,
  `sandbox_egress_denied`). Pull the tool source from the bundle
  to read what it actually does.

**Action:** identify which tool, which class, surface the error +
the most-likely fix.

### D. Wrong model behavior (no provider error)

**Recognize:** session `completed` but the user is unhappy. No
error events. The agent did something other than what was wanted.

**Evidence:** read the system prompt
(`revisions-system-prompt`) + the conversation
(`@posthog/agent-applications-sessions-retrieve` → `conversation` field). Compare the
agent's tool-call choices to what the prompt asks for.

Common subcategories:

- **Wrong tool chosen.** Agent had two tools, picked the worse
  one. Fix: clarify in `agent.md` or a skill which tool to use
  when.
- **Skill not loaded.** Agent had a relevant skill in
  `spec.skills[]` but never called `@posthog/load-skill` on it.
  Fix: tighten the `description` in the spec — it's the only
  signal the model gets.
- **Hallucinated tool / arg.** Agent called something that
  doesn't exist or with malformed args. Fix: framework preamble's
  `tool_failure_guidance` usually catches this on the next turn,
  but if it persists the prompt may be confusing the model about
  the surface.
- **Tone or format mismatch.** Agent returned the right
  information in the wrong shape. Fix: a Slack-thread-protocol-
  style skill that enforces the format.

**Action:** point at the specific prompt / skill line that drove
the wrong choice, and propose a one-paragraph edit. Don't
rewrite the whole thing.

### E. Approval timeout

**Recognize:** session state `failed` with
`failure_reason: approval_timeout`. Event log has an
`approval_requested` event without a matching `approval_decided`.

**Evidence:** the approval's `ttl_ms` (from
`spec.tools[].approval_policy`) and the timestamp gap. Default
24h.

**Action:** explain that the tool was gated, no human decided
in the window, the platform cancelled. Suggest either: a longer
TTL, a different approver list, or removing the approval
requirement if it was paranoia.

### F. Queued forever / never picked up

**Recognize:** session state `queued` for many minutes after
`started_at`. Worker hasn't claimed it.

**Evidence:** check whether any sessions on any agent are
running by listing recent sessions across the team. If nothing
is running, the worker pool is down — outside the agent's
control; surface to the user as a platform issue.

**Action:** identify whether it's session-specific (corrupted
spec / bundle?) or platform-wide (worker pool issue). Don't
guess at the latter; say "this is a platform-side issue, file
in #agents-platform-help" if confirmed.

### G. Trigger / auth failure (session never opened)

**Recognize:** the user says "the agent isn't responding" but
`@posthog/agent-applications-sessions-list` shows no recent session for
the trigger they expected.

**Evidence:** the trigger / auth path failed before a session
was created. For chat trigger this means a 401/403 from
`/agents/<slug>/run`. For slack it means the slack adapter
rejected (workspace not trusted, mention pattern wrong). For
webhook, the path/secret check failed.

**Action:** walk through the trigger config in the spec, check
the auth mode, surface what to verify on the caller side.

## Report shape

Once you have a hypothesis, produce a structured report. Don't
write a wall of text.

```text
**Session s_xyz789 — failed (limit_exceeded, max_tool_calls)**

Root cause: agent looped on `@posthog/query` 47 times without
making progress. Each call ran a near-identical query against
$pageview, only changing the `event` filter. The loop started at
turn 4 and continued until max_tool_calls.

Why: the system prompt asks the agent to "verify every metric you
report by re-querying", but doesn't say "do this once". Combined
with the skill `query-recipes` not having a stop condition, the
model kept verifying its own verifications.

Fix (small): in agent.md, change "verify every metric" → "verify
each metric you report at most once". Also bound the verification
in skills/query-recipes.

Fix (bigger): the agent doesn't really need verification at all
for digest use cases. Could drop the rule entirely.

Want me to: open the live revision so you can see the prompt? draft
a new draft with the small fix? read the full conversation log?
```

## What NOT to do

- **Don't suggest "just rerun"** without identifying the cause —
  if it failed once it'll fail again unless the cause is
  external (provider rate limit, integration outage).
- **Don't propose adding logging or instrumentation.** The
  session-logs already capture everything. If you want more
  signal, add a `console.log`-equivalent inside a custom tool —
  but that's invasive for a debug session.
- **Don't promise a fix you haven't verified.** A prompt edit
  might fix the bug or might break something else. Suggest the
  edit, recommend a test run with `running-and-evaluating-tests`,
  don't claim the bug is solved until tests pass.
