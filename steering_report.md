# Cloud steering implementation and hardening report

Date: 2026-07-16

## Status

Negotiated native steering for active Codex and Claude cloud runs is implemented and hardened against the original QA findings and all follow-up blocker rounds.

The implementation is split across:

- PostHog backend branch: `posthog-code/cloud-run-steering`
- PostHog Code branch: `posthog-code/cloud-run-steering-agent`

The latest fixes bound final child-to-parent signal delivery, let existing task-management histories adopt acknowledgement-first ordering on their next sandbox generation, and reconcile resume history by stable message identity instead of timestamps.

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
- A declined steer returns immediately without starting another turn inside the steering request.
- Temporal requeues the declined message at the front of the normal follow-up queue and delivers it after the active turn boundary.
- A real transport failure is propagated to the normal retry and failure machinery.

This prevents a healthy cloud run from receiving a terminal error because its active turn ended between the server check and the adapter call. It also keeps the Temporal loop free to deliver later steers while the requeued normal follow-up is active.

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

Workflow handlers accept the versioned signal and legacy histories. Production senders remain on the legacy signal until the receiver-first rollout gate is explicitly enabled after every task worker has the new handlers. Capability discovery is used only after that deployment barrier has been crossed.

## First follow-up blocker fixes

### Steering signals are capability-gated

`ProcessTaskWorkflow`, `TaskManagementWorkflow`, and `ExecuteSandboxWorkflow` expose a read-only steering protocol query.

Unsupported workflows and failed capability queries receive the durable legacy `send_followup_message` signal. Task management records the child workflow's protocol version and preserves historical signal choices during replay. The query is a per-workflow negotiation mechanism, not the rolling-deployment barrier.

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

## Latest blocker fixes

### Temporal signaling uses a receiver-first rollout

A capability query and the following signal can be handled by different worker versions, so the query alone cannot make an unsupported signal safe during a rolling deployment.

`TASKS_NATIVE_STEERING_SIGNALS_ENABLED` now provides the deployment barrier:

- Production defaults it to disabled, so senders keep using the durable legacy signal.
- The new workflow receivers are deployed first while the flag remains disabled.
- The flag is enabled only after every worker polling the task queue has the new signal handlers.
- Child workflow startup skips capability probing while the flag is disabled and remains successful if capability discovery later times out.

The rollout sequence is documented in `products/tasks/docs/CLOUD_COMMANDS.md` and covered in the external sender and child startup tests.

### Incomplete hydration preserves the count domain

When resumed hydration cannot produce a complete result, buffered updates are still chain-global. The renderer now initializes the release offset from `resumeFromEntryCount` instead of zero before it flushes those updates.

The regression uses a non-zero inherited count and verifies the buffered live event is appended rather than normalized away.

### Stale Codex turn IDs decline instead of failing the run

The app-server client now preserves JSON-RPC error codes. The Codex adapter recognizes the two stale-turn `-32600` responses from `turn/steer` and returns `steer: false` for an explicit steer.

Only those known boundary responses are converted to a decline. Network failures and unrelated app-server errors still propagate through normal retry and failure handling.

### Declined steering is requeued outside the request

An explicit agent-server steer is now a strict try-steer operation. It either joins the active turn or returns `steer_declined` immediately; it never waits for the owned turn and starts a normal prompt inline.

Both `ProcessTaskWorkflow` and `ExecuteSandboxWorkflow` consume that outcome, clear steer intent, and put the message at the front of the normal queue. This lets the Temporal loop deliver later steers concurrently while the fallback normal turn is running.

### Overlapping resume windows are deduplicated

Resume hydration now finds the maximum suffix/prefix overlap between ancestor history and the current endpoint response. This handles backend history windows that overlap without beginning at the root, avoiding duplicate transcript entries beyond the backend's bounded resume-chain window.

## Final race and delivery fixes

### Completion drains a declined-steer fallback

Both `ProcessTaskWorkflow` and `ExecuteSandboxWorkflow` now finish the active follow-up and drain follow-ups that became dispatchable before terminal cleanup.

If `complete_task` arrives while a steer attempt is in flight and that steer declines, the message is converted to a normal follow-up and delivered before the workflow exits. The behavior remains behind the existing Temporal patch so prior histories replay unchanged.

The regressions cover completion arriving during the steer attempt in both workflow generations.

### Cold-reload hydration updates the live watcher offset

The live watcher now owns the resume-history offset used to normalize chain-global updates. It starts from `resumeFromEntryCount` and is updated in place when hydration succeeds, including hydration triggered by a same-run reconciliation.

This keeps the existing watcher synchronized when an initial cold-reload hydration is incomplete and a later attempt succeeds. Buffered or subsequent leaf updates continue to append against the leaf-local cursor instead of being dropped as a gap.

### Recoverable outcomes remain idempotent

An accepted prompt that returns `error_recoverable` is now committed before the result is returned. A retry with the same `messageId` receives the original delivery outcome and cannot execute the prompt or its side effects again.

### Persisted resume history is authoritative during hydration

Live E2E exposed a separate immediate-resume duplication: inherited live `agent_message_chunk` events could be merged over already-coalesced persisted `agent_message` history because their JSON shapes differ.

Resume hydration now treats persisted history as authoritative through its newest event and appends only genuinely newer session events. Live watcher updates remain buffered until hydration completes, so no current-leaf update is lost. The regression preserves a newer live event while rejecting the inherited duplicate chunk.

## Latest ordering and hydration race fixes

### Declined and shutdown-rejected steers preserve arrival order

Every pending follow-up now receives a monotonic arrival sequence. A steer that is declined by the active sandbox or rejected during sandbox shutdown is converted to a normal follow-up and inserted according to that sequence instead of repeatedly being inserted at queue index zero.

The sequence is carried across task management, child workflow signaling, acknowledgement recovery, persistence, and restore. Regressions cover two declined steers and two shutdown-rejected steers and verify that `S1` remains ahead of `S2`.

### Workflow completion closes follow-up admission before teardown

Both workflow generations enter their closing state synchronously when the final follow-up drain begins. Work accepted before the terminal boundary is drained, while signals arriving after that boundary are rejected through the existing shutdown acknowledgement path instead of being accepted into a queue that will never run.

This removes the teardown window where `complete_task` could finish the workflow after a late steer had been admitted.

### Every resume hydration attempt buffers live updates

The cloud watcher now owns a hydration token and buffers live updates during initial hydration and every retry. A stale or overlapping hydration attempt cannot release another attempt's buffer.

On success, the hydrated history, leaf-local cursor, and history offset are installed atomically before buffered updates are replayed. This prevents a successful retry from resetting `processedLineCount` while a live update is being received.

### Same-timestamp events use exact event identity

Hydration no longer treats timestamps as the provenance boundary. Existing and hydrated events are compared using exact event keys, while the existing semantic coalescing rule still prevents persisted agent messages and their live chunk equivalents from rendering twice.

Distinct events that share a millisecond timestamp, including turn completion, errors, tool updates, and response chunks, are retained.

## Final drain, acknowledgement, and coalescing fixes

### Legacy final draining keeps follow-up admission open

New `ProcessTaskWorkflow` histories keep accepting follow-ups while the final active dispatch finishes. When that dispatch completes, the workflow closes admission and checks the queue synchronously before returning.

Existing histories preserve their prior command order through the `tasks-drain-followups-before-shutdown` Temporal patch. Regressions cover both the new admission behavior and replay-compatible legacy behavior.

### Child acknowledgements are ordered before completion

New `TaskManagementWorkflow` histories drain queued child acknowledgements before processing a queued child completion. The parent therefore removes an acknowledged message before completion recovery considers requeueing it.

The behavior is protected by the `tasks-task-management-ack-before-completion` Temporal patch so existing histories replay with their recorded command order.

### Child completion cannot overtake a failed acknowledgement

New `ExecuteSandboxWorkflow` histories preserve outbound order when a signal send fails. A failed acknowledgement and every later outbound signal are restored ahead of signals that arrived during the await, and finalization retries the ordered queue until it is empty.

This prevents a completion signal from succeeding after an earlier acknowledgement failed and avoids redelivering an already-executed follow-up in a replacement sandbox. Existing histories retain their prior behavior through the `tasks-execute-sandbox-ordered-outbound-delivery` Temporal patch.

### Persisted final responses supersede inherited chunk runs

Resume hydration uses the stable coalesced message boundary produced by `SessionLogWriter`. When persisted history contains an authoritative `agent_message`, inherited live `agent_message_chunk` events from the same coalesced response are discarded as one contiguous chunk run.

Exact event-key deduplication still preserves distinct same-timestamp completion, error, tool, and response events. The regression uses different partial and final text, so content-based deduplication cannot make it pass.

## Final parent delivery, replay, and hydration identity fixes

### Final child signaling is bounded

`ExecuteSandboxWorkflow` now treats closed or missing parent workflow errors as terminal delivery outcomes. It clears the pending acknowledgement/completion queue and lets the child workflow finish instead of retrying a parent that can no longer receive signals.

Transient final-delivery failures are capped at five attempts. After the retry budget is exhausted, the workflow logs the undelivered count, clears the queue, and terminalizes without growing Temporal history forever.

Regressions cover:

- A typed parent-not-found error stopping immediately without sleeping.
- Repeated transient failures stopping at the configured attempt limit.

### Existing histories adopt acknowledgement-first ordering per sandbox

The workflow-start patch remains in place so existing histories replay their recorded command order.

Task management now also evaluates a deterministic patch ID for each sandbox generation. A sandbox generation recorded by an old worker keeps its historical completion-before-acknowledgement order, while the next live sandbox generation records and enables acknowledgement-first processing.

The regression simulates an old generation followed by a new generation and verifies that a queued child acknowledgement removes the delivered message before completion recovery can requeue it.

### Resume merges use stable message identity

Live E2E exposed a timestamp-only mismatch after the first real resume: the persisted and live copies of the same leaf prompt differed by one millisecond, so both survived hydration.

Resume hydration now:

- Matches prompt turns by the JSON-RPC message identity, independent of timestamp.
- Deduplicates persisted and live events using message identity plus occurrence count, preserving repeated legitimate events.
- Matches authoritative final responses to live chunk runs by turn and assistant-message position.
- Mirrors `SessionLogWriter` chunk coalescing, including empty thought chunks that do not terminate a response chunk run.
- Retains unrelated events that share a millisecond timestamp.

The updated regression covers a persisted prompt whose timestamp differs from its live copy, a direct final message at a later timestamp than its partial chunks, and an unrelated same-timestamp response in the following turn.

## Automated validation

Latest validation:

- Backend `process_task` workflow suite: 48 passed.
- Backend `execute_sandbox` workflow suite: 61 passed.
- Backend `task_management` workflow suite: 62 passed.
- Focused PostHog Code session host suite: 142 passed.
- PostHog Code UI suite: 1,523 passed across 172 files.
- Core and UI TypeScript package typechecks passed.
- Ruff, Python compilation, Biome formatting and lint, and diff checks passed.

Earlier validation across the branch also covered the full UI and agent packages, OpenAPI generation, Python compilation, shared and agent typechecks, and the focused Temporal, activity, client, adapter, and app-server suites.

## Live cloud-run verification

### Final bounded-delivery and stable-hydration verification

- Task: `48c15ee2-b513-4d39-92be-71f45b0381f9`
- A run: `fef94ede-c588-43d6-9caa-39d18b9fb541`
- B run: `c3dae613-21ee-4cba-98d5-cbdf3e8d3354`
- C run: `52aa9a84-79d3-4f1b-ae39-60f525c7cdc8`

The current backend and PostHog Code working trees ran through the configured backend and LLM gateway tunnels.

Verified:

- A returned `BASE716FINAL` exactly twice: once in the prompt and once in the response.
- A normal turn started a 45-second terminal command. `NATIVESTEER716` appeared as a user message while that turn was still busy, then returned exactly once after the tool boundary.
- The superseded `UNSTEERED716` instruction remained exactly once as its original user message and produced no response.
- The first B hydration initially reproduced the review class of bug: `RESUMEB716` appeared three times because persisted and live prompt copies differed only by timestamp.
- After applying stable message-identity reconciliation and fully restarting Electron, B cold-hydrated with `RESUMEB716` exactly twice and one restored-sandbox boundary.
- B was terminalized before C was sent, producing a real resume-of-a-resume. C returned `RESUMEC716` exactly twice.
- A final full Electron restart loaded BASE, the active native steer, B, and C with every successful marker exactly twice, two restored-sandbox boundaries, no pending prompt, and no semantic session error.
- Read-only database state confirmed the exact A→B→C `state.resume_from_run_id` chain and `completed` status for all three runs.
- All three runs persisted durable sandbox snapshots:
  - A: `im-01KXN89A7487TKXXBEC1DKT9BT`
  - B: `im-01KXN8JJTMG2ND7JQEBH7QK45B`
  - C: `im-01KXN8Q8ENYXHZYGD43WXFD1WC`

A non-terminal local Git checkpoint warning reported an invalid cross-device rename during final teardown. It did not affect the Temporal run status, durable sandbox snapshots, transcript hydration, or the completed A→B→C resume chain, and it was unrelated to tunnel connectivity.

### Final drain and resume coalescing verification

- Task: `40d5e6f4-057b-49b2-bb71-2e52f0b22464`
- A run: `177e3659-18fa-4acd-968a-b5b518f0b8c1`
- B run: `f0b80ac1-4ffc-4718-a69d-d249589117bc`
- C run: `fd92730d-755c-4a6d-8ca4-8b27397a5ceb`

The backend worker and Electron app ran the current working trees through the active backend and LLM gateway tunnels.

Verified:

- A returned `BASE716ACK` exactly twice: once in the prompt and once in the response.
- A normal follow-up returned `FALLBACK716` exactly twice.
- A second normal follow-up started a 45-second terminal command. An active native steer returned `STEER716ACK` exactly twice, while the superseded `LONG716DONE` instruction remained exactly once as its user prompt and produced no response.
- The active steer left the run connected, without a terminal error or pending prompt.
- A and B were terminalized before the next message was sent, producing real A→B→C resumed runs.
- B returned `RESUMEB716ACK` exactly twice and C returned `RESUMEC716ACK` exactly twice after cold hydration.
- A full Electron process restart and task reopen loaded the entire transcript with all successful prompt/response pairs exactly once, the superseded long instruction once, and two restored-sandbox boundaries.
- The cold transcript had no error, no pending prompt, no missing ancestry, and no duplicate partial response.
- Read-only database state confirmed the exact A→B→C `state.resume_from_run_id` chain, and all three runs reached `completed`.

### Latest ordered steering and A-to-B-to-C cold hydration run

- Task: `0416caa0-2b6f-4ac9-a0ae-2d587b841c52`
- A run: `6bac2293-74ee-4fb3-b532-e1dd13c4d393`
- B run: `4afc569d-5d60-4a68-82ce-62ea915dbfa8`
- C run: `04254746-ec03-4144-9162-5070f02e19e0`

The backend and Electron app were fully restarted with the current working trees and replacement backend and LLM gateway tunnels. The test used a new task so the earlier failed-tunnel attempt could not affect the result.

Verified:

- A returned `BASE715NEW` exactly twice: once in the prompt and once in the response.
- A normal follow-up started a 25-second terminal command. An active steer then returned `STEER715NEW` exactly twice, while the superseded `FALLBACK715` instruction remained exactly once as its original user message.
- The active run remained healthy with no terminal error or pending prompt.
- A was completed before B was sent, and B was completed before C was sent. Local database state confirmed the exact A-to-B-to-C `state.resume_from_run_id` chain.
- B returned `RESUMEB715NEW` exactly twice and C returned `RESUMEC715NEW` exactly twice.
- A full Electron process restart and task reopen hydrated all four successful prompt/response pairs exactly once, retained the superseded fallback once, and displayed two restored-sandbox boundaries.
- The cold transcript had no error, no pending prompt, no missing ancestry, and no duplicate response.
- All three runs reached `completed`.

### Final steering and A→B→C hydration run

- Task: `3bd196b5-fd2b-4858-9ab2-f2eb07b29763`
- A run: `aed18219-01e6-4c0e-a0bb-5fe2e1343e2e`
- B run: `afb5674f-a4e5-4e72-bc04-6dfab9712766`
- C run: `4cada160-2626-44fc-ac3f-cd50ffba26cf`

The backend and Electron app were restarted with the current working trees. The live sandbox reported the configured backend and LLM gateway tunnels, and database state confirmed the final A→B→C linkage.

Verified:

- A returned `FINALGOOD15` once in the response and once in the echoed prompt.
- An idle steer became a normal fallback turn. While that request was active, a second steer was delivered concurrently through `send_followup_steered` and returned `STEERFINAL15` without terminalizing the run.
- A was completed before B was sent, and B was completed before C was sent. Both follow-ups therefore created real resumed runs rather than joining a live workflow.
- B returned `RESUMEFINAL15`; C returned `THIRDRESUME15`.
- Immediately after C hydrated, every prior and current marker appeared exactly twice, with no duplicate response chunks, missing ancestry, pending prompt, or error.
- After a cold renderer reload, all markers still appeared exactly twice and the transcript contained two restored-sandbox boundaries.
- A new post-reload live follow-up returned `POSTFIXLIVE15` exactly twice, proving the C watcher retained the correct leaf-local cursor after hydration.
- All three workflow runs reached `completed`.

### Latest Codex boundary, resume, and cold-reload run

- Task: `6f9dbb39-0c28-4dd0-9660-60534eeb705e`
- Initial run: `144fd125-df4c-40e2-bf29-371c1dceadab`
- Resumed run: `6cb2dc17-5e44-4ce7-b77d-e77232325e60`

Verified with the local Electron app, backend, Temporal worker, Modal sandbox, and LLM gateway:

- The baseline Codex turn returned `BASEJUL15` with one prompt and one response.
- A normal fallback follow-up started a 40-second terminal command at 12:42:55 UTC.
- While that follow-up was active, Temporal received `send_steer_message` at 12:43:06 UTC and logged `send_followup_steered`.
- The accepted steer appeared inside the same active turn and returned `STEER2JUL15`; the original fallback response was superseded, and the run had no terminal error.
- Completing the initial workflow and sending another message created a distinct resumed run linked through `state.resume_from_run_id`.
- The resumed run returned `RESUMEJUL15` and rendered exactly one restored-sandbox boundary.
- After a cold renderer reload, the baseline, fallback, accepted steer, restored boundary, resume prompt, and resume response were all present with no pending prompt or error state.
- A new post-reload follow-up returned `POSTRELOADJUL15`, proving that live events append after hydration without a cursor gap or transcript replacement.

The first cold sandbox boot exposed a local backend web-process stall while generated assets were reloading. Restarting only the backend web process restored both the local endpoint and tunnel; Temporal, the sandbox, and the run remained intact. The validation above was completed after recovery.

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

- Re-probe a child workflow after a transient two-second capability timeout instead of retaining safe queue-only behavior for that sandbox lifetime.
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
