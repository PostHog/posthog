# Cloud steering implementation and hardening report

Date: 2026-07-15

## Status

The negotiated native steering path for active Codex and Claude cloud runs is implemented, hardened against the five original high-priority QA findings and three follow-up blockers, verified with automated tests, and exercised end to end against the local PostHog backend and PostHog Code desktop app.

Both implementation branches were pushed with signed commits:

- PostHog backend branch: `posthog-code/cloud-run-steering`
  - Hardening commit: `2fe83bc1012` (`fix(tasks): harden cloud steering delivery`)
  - The follow-up capability-gating changes are in the commit containing this report.
- PostHog Code branch: `posthog-code/cloud-run-steering-agent`
  - Initial hardening commit: `4ddb8abea` (`fix(cloud): harden steering delivery and hydration`)
  - Follow-up race fix: `115678c56` (`fix(cloud): close steering delivery races`)

## What the feature does

- Negotiates native steering for active Codex and Claude cloud turns.
- Sends accepted steers to the live agent turn through the durable Temporal path.
- Delivers steer follow-ups concurrently while preserving FIFO ordering for normal queued follow-ups.
- Falls back to normal follow-up delivery when a steer can no longer join the active turn.
- Shows the Steer/Queue control for supported cloud sessions.
- Preserves Claude turn ordering until accepted steers are consumed.
- Hydrates the complete parent/resume transcript while retaining the current leaf run's live-log cursor.

## High-priority QA fixes

### 1. Failed Codex steers are no longer acknowledged as successful

The Codex adapter now propagates `turn/steer` transport failures. It calls `onSteered` and broadcasts the user prompt only after Codex accepts the RPC.

Explicit steer attempts made after the active turn has ended return a declined steer result instead of starting an unrelated turn or emitting a false prompt echo.

Regression coverage verifies that a rejected `TURN_STEER` call produces no steer acknowledgement and no user-prompt broadcast.

### 2. Turn-boundary races fall back safely

The agent server now treats adapter-level steering as an accept-or-decline operation:

- An accepted steer joins the active turn.
- A declined steer waits for the owned turn to become idle and then uses the normal follow-up path.
- A real transport failure is still propagated for the normal retry and failure machinery.

This prevents a healthy cloud run from receiving a terminal error merely because its active turn ended between the server's initial check and the adapter call.

### 3. Steer intent does not survive sandbox replacement

Shutdown-rejected and unacknowledged follow-ups are now requeued with `steer=False` whenever they cross a sandbox-session boundary.

The original steer intent is preserved only while it still targets the same live sandbox execution. A replacement sandbox therefore receives the message as a normal queued follow-up rather than injecting it into a different initial or resumed turn.

### 4. Partial resume hydration is detected and retried

The PostHog API client now returns explicit completeness metadata with fetched session logs. A failed or incomplete page can no longer look like a successful empty response.

Resume hydration now:

- Avoids marking an incomplete parent/leaf fetch as hydrated.
- Retries incomplete hydration during later reconciliation.
- Deduplicates concurrent hydration calls with one in-flight promise per run.
- Merges parent-chain history with current leaf entries.
- Keeps full transcript length separate from the leaf run's live stream cursor.
- Preserves leaf log offsets when the current endpoint returns a full-chain snapshot.
- Buffers incoming live cloud updates while hydration is in progress, then applies them without dropping or duplicating entries.
- Clears stale pending and Thinking state after the reconciled history becomes authoritative.

Regression coverage includes leaf-only responses, full-chain responses, ancestor-fetch failure followed by retry, and live events arriving during hydration.

### 5. Temporal steering signals are rolling-deployment safe

New senders use the versioned `send_steer_message` signal while keeping the existing positional arity of legacy follow-up signals unchanged.

Workflow handlers accept both the versioned signal and the legacy form, including histories containing the earlier optional steer argument. This prevents old or sticky workers from failing workflow tasks because a new sender appended an unexpected positional argument.

Tests cover both signal formats and replay-compatible dispatch behavior.

## Additional QA finding resolved

Finding 7, concurrent resume hydration without in-flight deduplication, was resolved as part of the hydration work. Each run now reuses one active hydration promise and clears it in `finally` so later retries remain possible.

## Follow-up blocker fixes

### 1. Steering signals are capability-gated during rolling deployments

The backend now exposes a versioned, read-only steering protocol query on every workflow that can receive a follow-up:

- `ProcessTaskWorkflow`
- `TaskManagementWorkflow`
- `ExecuteSandboxWorkflow`

External senders query the target workflow before selecting the signal. A workflow that supports protocol version 1 receives `send_steer_message`. An old worker, an unsupported workflow, or a failed query receives the legacy `send_followup_message` signal instead, so the message remains deliverable as a normal queued follow-up.

The task-management parent also records the child workflow's protocol version when the sandbox workflow starts. It only sends the versioned child signal when that receiver advertised support. A Temporal patch preserves the exact signal choice of histories created before capability gating was added.

Regression coverage verifies supported receivers, old receivers, failed capability queries, and replay of histories that predate the new patch.

### 2. Concurrent retries share the original message outcome

The agent server now stores one in-flight delivery promise per `messageId`. A concurrent retry with the same ID waits for the original request instead of returning `duplicate_delivery` early.

Both callers therefore observe the same success or failure. If the original fails, the ID is removed from completed delivery tracking and a later retry can deliver it normally.

The regression rejects the original adapter request while a duplicate is waiting, verifies both requests receive the same failure, and verifies the adapter was invoked only once.

### 3. Immediate resume keeps history and stream counts separate

Cloud-task watchers now retain the initial `resumeFromEntryCount` and pass it through every hydration path. When immediate resume starts with ancestor history already in the session, hydration no longer folds that history count into the leaf run's `processedLineCount`.

The watcher always computes the history-to-leaf offset after hydration, including when `resumeFromEntryCount` is defined. Buffered live updates are then compared against the leaf-local cursor and appended without replacing the complete parent chain.

The regression covers ancestor history, a defined resume count, leaf-only hydration, and a buffered live update that arrives before hydration completes.

## Automated validation

Latest follow-up validation:

- Backend Temporal and client suite: 183 passed.
- PostHog Code agent server suite: 113 passed.
- PostHog Code session service UI suite: 139 passed.
- Agent, core, and UI TypeScript package typechecks passed.
- Ruff, Biome, Python compilation, and diff checks passed.
- The PostHog Code commit hook reran Biome and the full workspace typecheck successfully.

Earlier hardening baseline:

- Backend targeted post-merge tests: 138 passed.
- PostHog Code agent package: 77 files and 1,266 tests passed.
- PostHog Code UI package: 172 files and 1,519 tests passed.
- API client package: 91 tests passed.
- Full PostHog Code workspace typecheck: 23 tasks passed.
- Four focused TypeScript package typechecks passed.
- Ruff, Biome, Python compilation, OpenAPI generation, preflight, and diff checks passed.
- The final PostHog Code commit hook reran Biome and the full workspace typecheck successfully.

## Live cloud-run verification

### Follow-up blocker E2E

- Task: `a4068ba3-315c-4d90-887f-bd1f0e0246bc`
- Parent run: `8eb59301-ac7e-4787-9f18-6a10585f1881`
- Resumed leaf run: `50dd734f-dc03-4ac5-8834-e247fac664c2`

Verified against a fresh capability-aware workflow and a fully restarted Electron main process:

- A normal follow-up entered the active Claude turn.
- A second message was delivered through the native steer path while that follow-up was running.
- Temporal recorded the accepted steer and the run completed without an error or duplicate prompt.
- The parent run was made terminal with `complete_task`, including snapshot creation.
- Sending the next message created a real resumed leaf run.
- Immediate resume retained the parent transcript, one `Restored sandbox` marker, and the new leaf response.
- A cold renderer reload retained the same order and counts with no missing ancestry, leaf-only replacement, duplicate response, or stuck Thinking state.

### Codex

- Task: `849b13f1-4f27-4a48-9a19-c6effac42fe9`
- Parent run: `db74f772-79ad-4f8b-8343-ea6ec157d020`
- Resumed leaf run: `85a092ba-c16e-4375-a6ca-275116000a48`

Verified:

- Steering an active initial turn.
- Steering while an active follow-up was running.
- Queue ordering for normal follow-ups.
- Idle/turn-boundary fallback to normal delivery.
- A real resume created from a completed parent run.
- Parent and leaf transcript hydration after a complete Electron restart and cold reopen.
- No stuck busy state, terminal error sentinel, missing ancestry, skipped leaf event, or duplicate hydrated response.

### Claude

- Task: `1331c8fb-dda0-4928-8285-2dfac185895d`

Verified:

- Steering during the initial turn.
- Steering during an active follow-up.
- The original turn remains open until the accepted steer is consumed.
- Cold reopen restores the completed transcript without errors or premature `turn_complete` behavior.

## Remaining non-blocking QA findings

The merge-blocking work addressed findings 1 through 5 and finding 7. The following yellow or green recommendations remain separate follow-ups:

- Finding 6: reduce redundant full-chain reads and use stable entry identifiers for cheaper deduplication.
- Finding 8: reconcile rapid optimistic steer messages using stable client message IDs.
- Finding 9: restore failed cloud steers to the queue with an actionable error state.
- Finding 10: enable per-message cloud steering in the queued-message dock.
- Finding 11: negotiate an end-to-end cloud steering protocol version across every deployment layer.
- Finding 12: carry a stable idempotency UUID from the command API through delivery.
- Finding 13: replace repeated steer-priority list scans with separate queues or an index.

The QA security review found no new authorization, cross-task access, injection, secret exposure, or unsafe URL issue.

## Scope hygiene

The pre-existing backend changes in `products/tasks/backend/logic/services/sandbox.py` and the untracked `tools/load-posthog-code-env.sh` were left unchanged. They were not included in the steering commits.
