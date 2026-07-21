# Skill — orchestrating live agents

How to drive a LIVE (promoted) agent as an orchestrator: start a
session, watch it work, steer it mid-run, stop it when it's off the
rails, and dig into what happened. This is the runtime loop —
authoring/editing is `editing-agents-safely`, failure forensics
in depth is `debugging-sessions`.

## The orchestration loop

```text
invoke → poll listen (cursor) → done? ──yes──> read the result
              │                          no
              │  off-track? ──> send (steer)  ──┐
              │  hopeless?  ──> cancel (stop)   │
              └───────────────<─────────────────┘
```

1. **Invoke.** `posthog__agent-applications-invoke` with the opening
   `message`. Requires the agent to have a live revision and a `chat`
   trigger. Returns `session_id` (state `queued`). Pass an
   `external_key` if you want a repeat invoke to resume the same
   session instead of starting a new one (idempotency / threading).

2. **Poll listen.** `posthog__agent-applications-listen` with the
   `session_id`. Returns a compact digest: `state`, `turns` (total
   messages so far), `digest` (last assistant text + one-line tool
   activity), `next_cursor`, and `done`. Pass `next_cursor` back as
   `cursor` on every subsequent call so the digest summarizes only
   what's new. Stop polling when `done` is true — that means the
   current turn finished (`completed`, still open) or the session
   ended (`closed` / `cancelled` / `failed`).

3. **Judge from the digest.** The digest is deliberately payload-free
   — enough to tell on-track from off-track, not enough to audit the
   work. If a poll shows the agent looping on a tool, chasing the
   wrong subtask, or burning turns without progress, steer or stop
   (below). If you need the actual payloads to judge, drill down
   (last section) before deciding.

4. **Act on the outcome.** `completed` means the session is idle but
   OPEN — send a follow-up to continue the same conversation. Only
   `closed` / `cancelled` / `failed` are terminal.

## Steering: send is a mid-turn injection

`posthog__agent-applications-send` does more than continue an idle
session. If the session is `running`, the message buffers to the
session's pending inputs and is drained into the conversation at the
agent's next model-call boundary — the agent picks up your
correction without losing any work in progress.

Use it when the agent is drifting but the work so far is good:

```text
send: "Stop checking the EU cluster — the report only needs US data.
Finish the US summary and skip the rest."
```

Sends never race each other: multiple sends buffer in arrival order
and drain together at the next turn boundary.

## Cancel: the stop button

`posthog__agent-applications-cancel` with the `session_id`. Semantics
worth knowing before you press it:

- **It aborts the current model call.** Everything already done is
  kept — partial assistant text is persisted to the conversation.
- **A cancel that interrupts an actively-running turn reopens the
  session** as `completed` (open) — you can keep sending to it. The
  point is "stop what you're doing", not "end the conversation".
  The reopen is the runner's job and takes a few seconds: right
  after the cancel returns, listen still shows `cancelled`.
- **A cancel landing on an idle session terminalizes it** as
  `cancelled` — that's how you end a conversation you're done with.
- **Never cancel a `queued` session no worker has claimed yet**
  (e.g. right after invoke) if you intend to keep using it. It is
  neither actively-running nor idle: there is no runner to reopen
  it, so the cancel is permanently terminal and the pending turn is
  dropped silently. To redirect a just-invoked session, steer it
  with a plain send instead.
- **Idempotent on terminal sessions**: cancelling an already-
  `failed` / `cancelled` / `closed` session returns
  `idempotent: true` and changes nothing. Safe to fire twice at a
  terminal session — but not as a blind retry elsewhere: if the
  first cancel's turn has already reopened the session, a second
  cancel lands on an idle session and terminalizes it.

**The hard redirect is cancel + send — mind the settle window.**
Cancel kills the wayward turn immediately (a plain send would wait
for the current turn to finish on its own), but the runner's reopen
is asynchronous: for a few seconds the session still reads
`cancelled`, and a send in that window gets a false 410. Poll listen
until the state leaves `cancelled` (done, with the reopened
`completed` state) — only a cancel that interrupted a running turn
reopens; a cancelled `queued` session stays `cancelled` forever (see
the `queued` bullet above) — then send the corrective message to
re-queue the session pointed the right way.

```text
cancel  → { state: "cancelled", idempotent: false }  # turn aborted, work kept
listen  → { state: "completed", done: true }         # runner reopened it
send: "Wrong repo — do all of that against posthog/posthog.com
instead."                                            # re-queues, agent resumes
```

## Drilling down when the digest isn't enough

Two tools turn a suspicious digest into evidence:

**Transcript tail — `posthog__agent-applications-sessions-retrieve`
with `last_n`.** The digest's `next_cursor` is your high-water mark
of messages seen and `turns` is the conversation length, so the
messages you haven't inspected are exactly:

```text
last_n = turns − <your cursor from the previous listen>
```

That fetches full payloads (assistant text, tool calls, tool
results) for only the new tail — no re-reading a 200-message
conversation. `conversation_trimmed: true` confirms the trim;
`usage_total` is still computed over the whole session.

**Failure forensics — `posthog__agent-applications-session-logs` with
`level=error`.** The structured event log is the runner's own record
(tool executions, MCP open failures, identity resolution, approval
gates, errors) — separate from the transcript. Filtering to `error`
gives you the shortlist of what actually went wrong; each entry
carries structured metadata pointing at the failing tool / MCP /
turn. For the full failure taxonomy and what to do per class, read
the `debugging-sessions` playbook.

## What NOT to do

- **Don't poll listen in a tight loop.** Turns take seconds to
  minutes; poll on a human-ish cadence and use the `cursor` so each
  poll is cheap.
- **Don't re-invoke to "retry".** A fresh invoke starts a new session
  with no memory of the last one. If the session is `completed`,
  send into it; if it failed, read the logs first — the retry will
  fail the same way unless the cause was external.
- **Don't use cancel as a pause.** There is no resume-exactly-here:
  an interrupted turn's remaining work is gone (only its partial
  output is kept). Cancel means "that turn was wrong"; steering with
  send is the gentler tool when the work should continue.
- **Don't drive a draft this way.** invoke/send/cancel/listen target
  the LIVE revision only. For a draft, use
  `agent-applications-preview-proxy` (same `run` / `send` / `cancel`
  / `listen` shapes, Django-mediated).
