# Cloud steering implementation and hardening report

Date: 2026-07-15

## Status

Negotiated native steering for active Codex and Claude cloud runs is implemented and hardened against the original QA findings and both follow-up blocker rounds.

The implementation is split across:

- PostHog backend branch: `posthog-code/cloud-run-steering`
- PostHog Code branch: `posthog-code/cloud-run-steering-agent`

The latest fixes cover bounded Temporal capability discovery, multi-generation resume hydration, and idempotent agent delivery during teardown.

## What the feature does

- Negotiates native steering for active Codex and Claude cloud turns.
- Sends accepted steers to the live agent turn through a durable Temporal path.
- Delivers steer follow-ups concurrently while preserving FIFO ordering for normal queued follow-ups.
- Falls back to normal follow-up delivery when a steer can no longer join the active turn.
- Shows the Steer/Queue control for supported cloud sessions.
- Preserves Claude turn ordering until accepted steers are consumed.
- Hydrates the complete parent/resume transcript while retaining the current leaf run's live-log cursor.

## Original high-priority QA fixes

### Failed Codex steers are not acknowledged as successful

The Codex adapter propagates `turn/steer` transport failures. It calls `onSteered` and broadcasts the user prompt only after Codex accepts the RPC.

Explicit steer attempts made after the active turn has ended return a declined steer result instead of starting an unrelated turn or emitting a false prompt echo.

### Turn-boundary races fall back safely

The agent server treats adapter-level steering as an accept-or-decline operation:

- An accepted steer joins the active turn.
- A declined steer waits for the owned turn to become idle and then uses the normal follow-up path.
- A real transport failure is propagated to the normal retry and failure machinery.

This prevents a healthy cloud run from receiving a terminal error because its active turn ended between the server check and the adapter call.

### Steer intent does not survive sandbox replacement

Shutdown-rejected and unacknowledged follow-ups are requeued with `steer=False` when they cross a sandbox-session boundary.

The original steer intent is preserved only while it still targets the same live sandbox execution. A replacement sandbox receives the message as a normal queued follow-up.

### Partial resume hydration is detected and retried

The API client returns explicit completeness metadata with fetched session logs. A failed or incomplete page cannot look like a successful empty response.

Resume hydration:

- Does not mark incomplete parent or leaf data as hydrated.
- Retries incomplete hydration during later reconciliation.
- Deduplicates concurrent hydration with one in-flight promise per run.
- Merges parent history with current leaf entries.
- Keeps full transcript length separate from the leaf live-stream cursor.
- Preserves leaf log offsets when the current endpoint returns a full-chain snapshot.
- Buffers incoming live updates during hydration and applies them afterward.
- Clears stale pending and Thinking state after reconciliation.

### Temporal steering signals are rolling-deployment safe

New senders use the versioned `send_steer_message` signal while preserving the positional arity of legacy follow-up signals.

Workflow handlers accept the versioned signal and legacy histories. Capability discovery chooses the new signal only for receivers that advertise protocol version 1.

## First follow-up blocker fixes

### Steering signals are capability-gated

`ProcessTaskWorkflow`, `TaskManagementWorkflow`, and `ExecuteSandboxWorkflow` expose a read-only steering protocol query.

Unsupported workflows and failed capability queries receive the durable legacy `send_followup_message` signal. Task management records the child workflow's protocol version and preserves historical signal choices during replay.

### Concurrent retries share the original message outcome

The agent server stores one in-flight delivery promise per `messageId`. A concurrent retry waits for the original request instead of returning `duplicate_delivery` before the result is known.

Both callers observe the same success or failure. If the original fails before acceptance, the ID is released for a later retry.

### Immediate resume keeps history and stream counts separate

Cloud watchers keep inherited transcript history separate from the leaf run's `processedLineCount`. Buffered live updates compare against the leaf cursor and append without replacing the parent chain.

## Final blocker fixes

### Capability queries have a bounded deadline

Both external follow-up delivery and child workflow startup now query `steering_protocol_version` with a two-second RPC timeout.

A timeout, unavailable worker, or unsupported query is treated as protocol version 0:

- External delivery immediately falls back to the durable legacy signal.
- A successful Signal-With-Start remains successful even if the subsequent capability query fails.

Regression coverage verifies the explicit deadline and timeout fallback in both call paths.

### Resume-of-a-resume uses the correct transcript count

PostHog Code now stores two independent counters:

- `cloudTranscriptEntryCount`: the full inherited transcript count used to start the next resume.
- `processedLineCount`: the current leaf's local cursor used for live reconciliation.

When B resumes into C, C receives B's full A+B transcript count and starts with a zero leaf cursor. Hydration and live updates keep both values current without converting one into the other.

The regression covers A→B→C with a buffered C update and verifies the inherited A/B history, C hydration, and new live C event all remain present.

### Teardown cannot reopen an executed message ID

The agent server snapshots the accepted session before invoking the adapter and uses that session for post-turn log extraction and response handling.

A message ID becomes committed immediately after a steer is accepted or a normal prompt resolves. Failures after that commit point do not remove it, even if concurrent teardown clears the active session. Only failures before acceptance release the ID for retry.

The regression clears the active session after the adapter accepts the prompt, then verifies the original request succeeds and a retry returns `duplicate_delivery` without invoking the adapter again.

## Automated validation

Latest validation:

- Backend Temporal and client suite: 184 passed.
- PostHog Code agent package: 77 files and 1,268 tests passed.
- PostHog Code session service UI suite: 140 passed.
- Shared, agent, core, and UI TypeScript package typechecks passed.
- Ruff, Python compilation, and targeted Biome checks passed.

Earlier validation across the branch also covered OpenAPI generation, full package tests, workspace typechecks, and diff checks.

## Live cloud-run verification

### A→B→C resume-of-a-resume regression

- Task: `a234c4bd-bea5-43c3-8cb5-83e197742978`
- A run: `0894cd15-a916-4b53-822a-341e76e981bf`
- B run: `9f7f982e-b3d7-43ab-b193-c181e6b47f48`
- C run: `7a17077a-d56e-4e1b-80db-866fdd2e3439`

The run used a freshly restarted backend and Electron app with the current local checkouts.

Verified:

- A completed normally, then was made terminal in Temporal before B was sent.
- B was a distinct resumed run, completed normally, and was made terminal before C was sent.
- C was a second-generation resume and displayed the restored-sandbox boundary.
- Before the final reload, C retained the full chain with `cloudTranscriptEntryCount=158` and a C-local `processedLineCount=39`.
- After a cold renderer reload, the chain hydrated to 172 entries with a leaf-local cursor of 53.
- The semantic transcript contained all A, B, and C prompts and responses, two restored-sandbox boundaries, ten conversation items, no pending prompt, and a complete final turn.
- Database state confirmed all three distinct runs reached `completed`.

### Earlier Codex and Claude steering coverage

Live runs also verified:

- Steering an active initial turn.
- Steering while a follow-up was active.
- Queue ordering for normal follow-ups.
- Idle and turn-boundary fallback to normal delivery.
- Claude keeps the original turn open until accepted steers are consumed.
- Parent and leaf transcript hydration after Electron restart and cold reopen.
- No terminal error sentinel, duplicate prompt, missing ancestry, skipped leaf event, or stuck Thinking state in the tested paths.

## Remaining non-blocking QA findings

The merge-blocking findings are addressed. The remaining recommendations are separate follow-ups:

- Reduce redundant full-chain reads and use stable entry identifiers for cheaper deduplication.
- Reconcile rapid optimistic steer messages using stable client message IDs.
- Restore failed cloud steers to the queue with an actionable error state.
- Enable per-message cloud steering in the queued-message dock.
- Negotiate an end-to-end protocol version across every deployment layer.
- Carry a stable idempotency UUID from the command API through delivery.
- Replace repeated steer-priority list scans with separate queues or an index.

The QA security review found no new authorization, cross-task access, injection, secret exposure, or unsafe URL issue.

## Scope hygiene

The pre-existing backend changes in `products/tasks/backend/logic/services/sandbox.py` and the untracked `tools/load-posthog-code-env.sh` remain unchanged and are not part of the steering commits.
