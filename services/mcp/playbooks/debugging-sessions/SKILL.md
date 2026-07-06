# Skill — debugging sessions

How to diagnose a failing or anomalous session — taxonomy of
failures, where to look for each, and what to surface to the user.

## First — establish what 'failing' means

The user might say "broken" when they mean any of:

- The session state ended in `failed`
- The session ended in `completed` but the output was wrong
- The session ran longer / cost more than expected
- The session asked for human approval and the approval TTL expired
  (note: this does NOT fail the session — the janitor re-queues it)
- The session hung (`running` for too long, or `queued` and never
  picked up)

Real session states: `queued | running | completed | closed |
cancelled | failed`. There is no `errored` / `stuck` / `waiting`.

Ask one clarifying question if it isn't obvious from the trigger.
Then pick the matching branch below.

## The standard debug flow

1. **Pre-focus the session** if you have `focus_session`:
   `{ kind: 'session', session_id: <id> }`.

2. **Retrieve the session**.
   `posthog__agent-applications-sessions-retrieve` returns the conversation,
   the principal, the state, started_at, ended_at, usage_total,
   trigger metadata.

3. **Retrieve the logs**.
   `posthog__agent-applications-session-logs` returns the structured event
   stream. The event kinds (`SessionEventKind`) are:
   `session_started | turn_started | user_message | assistant_text |
tool_call | tool_result | client_tool_call | client_tool_result |
completed | closed | failed`. There is no separate
   `approval_requested` / `approval_decided` event — approvals surface
   as a sub-field on `tool_result` (see taxonomy section E).

4. **Identify the failure class** from the taxonomy below.

5. **For each non-trivial failure** pull the revision (so you can
   reason about the agent's design, not just the symptom) — same
   calls as the `reading-an-agent` playbook step 2 + 4.

6. **Produce a structured report** — see the report shape at the
   bottom.

For evidence beyond the conversation JSON — what the model actually
saw, per-turn latency/cost, which tool span errored — load
`querying-ai-observability` and HogQL the session's trace
(`$ai_trace_id` = the session id). The `$ai_generation` / `$ai_span`
events the runner captured into the team's project are the ground
truth for "where did the turn go wrong", and let you cite a specific
turn + error rather than inferring from prose.

## Failure taxonomy

The failure modes that account for almost every broken session.
For each: how to recognize it, where the evidence lives, what to
suggest.

Every terminal `failed` session carries a `reason` in its `failed`
log entry. The driver emits exactly four reasons:
`max_turns_exceeded`, `model_error`, `output_truncated`,
`loop_error`. There is no `limit_exceeded` and no `approval_timeout`.
(`max_tool_calls` / `max_wall_seconds` are not enforced as failure
reasons — only `spec.limits.max_turns` produces a terminal failure.)

For owner-facing triage the failure also maps to a coarse
`FailureCategory` bucket: `transient_infra | configuration |
quota_exhausted | tool_error | unknown`. Use these as the top-level
classification.

### A. Model / provider error (`model_error`)

**Recognize:** session state `failed` with reason `model_error`.
This is the catch-all for an errored model turn (the assistant
turn's `stopReason` was `error`). The raw provider/gateway error
string lives in the `failed` log entry's `reason` field (owner-
facing only — the bus event payload is deliberately empty).

**Evidence:** the `failed` log entry carries `reason` plus a
`source` (`ai_gateway` vs `provider`), `model`, `provider`, and
`api`. The matching `$ai_generation` event for the failing turn
also has `is_error: true` and the error string. Common underlying
causes: provider rate limit / overload (often categorized
`quota_exhausted` via the `429` / `rate_limit` patterns), context
length exceeded, bad API key (categorized `configuration`).

**Action:** report the raw reason + the immediate cause + the fix.
A rate-limit/overload generally clears on re-run; the platform
doesn't auto-retry mid-session. A context-length error wants
shorter skills or a tighter `spec.resume` compaction policy. A bad
key needs an admin.

### B. Turn cap hit (`max_turns_exceeded`)

**Recognize:** session state `failed` with reason
`max_turns_exceeded` (category `quota_exhausted`). The session ran
`spec.limits.max_turns` turns and the last turn still wanted to
continue (had tool calls).

**Evidence:** the spec's `limits.max_turns` vs the session's turn
count. Look at the last 3-5 turns to see what the agent was doing
when it ran out.

Common pattern: agent loops between two tools without making
progress (e.g. `read` then `read again`). That's a prompt issue,
not a limit issue — raising `max_turns` would just delay the loop.

**Action:** classify the loop. If real progress was happening,
suggest raising `max_turns` (and quote the new number). If a loop,
read the relevant skill / agent.md and suggest the prompt change
that breaks it.

### C. Tool error

**Recognize:** `tool_result` event with `ok: false`. The agent's
next turn usually acknowledges or retries. (A tool error does not
by itself fail the session — the model sees the failed result and
decides what to do. A failure mode dominated by tool errors
categorizes as `tool_error`.)

**Evidence:** the `tool_result` event carries `ok` (boolean) and,
when `ok: false`, an `error` string. Classify the source:

- **Native tool error** — e.g. `@posthog/slack-post-message`
  returns a Slack API 403. The runner faithfully relays the
  provider's error. Fix is usually integration / permission, not
  the agent.
- **MCP tool error** — the remote MCP server returned an error, or
  the MCP failed to open at session start (surfaced to the model in
  the system prompt as an unavailable capability). Check whether the
  MCP endpoint in `spec.mcps[]` is up (the runner doesn't health-
  check it; you may need to `posthog__agent-applications-sessions-list`
  for other agents using the same MCP to confirm cross-impact).
- **Custom tool error** — the sandboxed code threw or the sandbox
  killed it. Pull the tool source from the bundle to read what it
  actually does.

**Action:** identify which tool, which class, surface the error +
the most-likely fix.

### C2. Output truncated (`output_truncated`) / loop error (`loop_error`)

**Recognize:** session state `failed` with reason `output_truncated`
or `loop_error`.

- `output_truncated` — the model turn stopped on `length` (it hit
  the output-token ceiling mid-response). Category `quota_exhausted`.
  Evidence: the resolved max-output-tokens for the session (clamped
  against the model ceiling) vs how long the truncated turn was.
  Fix: raise `spec.limits.max_output_tokens` (within the model's
  ceiling) or ask the agent to produce shorter output.
- `loop_error` — the agent loop itself threw (an unhandled error in
  `runAgentLoop`, not a model stopReason). This is the fallback
  reason when an exception escapes the loop. The raw error string is
  in the `failed` log entry. Often categorizes as `transient_infra`
  (sandbox/redis/postgres/network patterns) or `unknown`.

**Action:** for `output_truncated`, quote the current vs suggested
token ceiling. For `loop_error`, surface the raw error + `source`
(gateway vs provider) from the log entry; a `transient_infra`-class
one may clear on re-run, an `unknown` one needs the owner to dig in.

### D. Wrong model behavior (no provider error)

**Recognize:** session `completed` but the user is unhappy. No
error events. The agent did something other than what was wanted.

**Evidence:** read the system prompt
(`revisions-system-prompt`) + the conversation
(`posthog__agent-applications-sessions-retrieve` → `conversation` field). Compare the
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

### E. Approval expired (does NOT fail the session)

**Recognize:** a gated tool call surfaces as a `tool_result` event
with an `approval` sub-field: `{ request_id, state }` where `state`
is one of `queued | approved | expired`. There are no separate
`approval_requested` / `approval_decided` events. A pending gate
shows `state: queued`; an approved call shows `state: approved` on
its (re-dispatched) `tool_result`.

On TTL expiry the janitor sweep sets the approval to `expired`,
appends a synthetic `{ approval: { request_id, state: 'expired' } }`
message to the session's `pending_inputs`, and **re-queues the
session** (state → `queued`). It does NOT fail the session — the
model wakes up, sees the expired envelope, and decides how to
proceed. So a session waiting on a stale approval looks like a
`queued` (or re-`running`) session with a `queued`-state approval in
its log, not a `failed` one.

**Evidence:** the approval's expiry comes from the tool's
`approval_policy`. Default approval TTL is 24h. (This Agent Builder's
own promote / archive gated tools use a 15-minute / `900000`ms TTL.)
Compare the `queued` approval's timestamp against now.

**Action:** if the user is surprised a gated action never happened,
explain it was waiting on a human approval that expired, the session
was re-queued, and the model moved on. Suggest a longer TTL, a
different approval `type`, or removing the approval requirement if it
was paranoia.

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
`posthog__agent-applications-sessions-list` shows no recent session for
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
**Session s_xyz789 — failed (max_turns_exceeded)**

Root cause: agent looped on `@posthog/query` across 47 turns
without making progress. Each call ran a near-identical query
against $pageview, only changing the `event` filter. The loop
started at turn 4 and continued until max_turns.

Why: the system prompt asks the agent to "verify every metric you
report by re-querying", but doesn't say "do this once". Combined
with the skill `query-recipes` not having a stop condition, the
model kept verifying its own verifications.

Fix (small): in agent.md, change "verify every metric" → "verify
each metric you report at most once". Also bound the verification
in skills/query-recipes. (Raising `max_turns` would only delay the
loop, not break it.)

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
