# Cloud steering implementation and hardening report

Date: 2026-07-16

## Status

Negotiated native steering for active Codex and Claude cloud runs is implemented and hardened against the original QA findings and all follow-up blocker rounds.

The implementation is split across:

- PostHog backend branch: `posthog-code/cloud-run-steering`
- PostHog Code branch: `posthog-code/cloud-run-steering-agent`

The latest fixes patch-gate closed-child recovery for existing Temporal histories, clear all stale steer intent at sandbox boundaries, bound repeated replacement attempts, and reconcile resumed transcripts by ordered prompt occurrence instead of global prompt identity.

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

## Closed-child recovery, replay-safe retry bounds, and turn-scoped hydration

### Final outbound retry exhaustion no longer strands the parent

The child still bounds transient final acknowledgement and completion delivery for new histories, but a later parent signal to an already-closed child is now a recovery event instead of an indefinitely armed dead session.

Task management:

- Recognizes typed child workflow closed/not-found signal failures.
- Reconciles acknowledgements already queued at the parent before deciding which slots remain unacknowledged.
- Requeues unacknowledged follow-ups in their original arrival order.
- Clears stale steer intent when the message crosses into a replacement sandbox.
- Resets per-sandbox capability, heartbeat, and CI state.
- Persists the restored queue before lazily starting the replacement sandbox.

The same recovery runs when the initial signal fails or an acknowledgement retry discovers that the child has closed. Regressions cover replacement startup and multiple stale follow-ups restored in sequence.

### The five-attempt final retry bound is replay-safe

The bounded final retry behavior is selected with a new Temporal patch at the retry boundary.

- New histories record the patch and stop after the configured five transient failures.
- Existing histories without the patch preserve the earlier unbounded retry command sequence.
- Closed or missing parent errors remain terminal immediately.

The regression models an existing history that has already passed the new limit and verifies that it continues to its recorded successful delivery instead of stopping early.

### Hydration deduplication is ordered and turn-scoped

Resume hydration no longer removes events using a transcript-wide count of serialized message payloads.

Hydrated events are grouped by their `session/prompt` turn and consumed in order only within the matching live turn. An identical completion or final response emitted by a later turn therefore remains present even when an earlier turn persisted the same payload.

The authoritative-final versus inherited-chunk reconciliation now stores each prompt key once with a set of assistant message positions. It no longer embeds a potentially large prompt in a new string for every response position.

The regression includes two turns with identical completion payloads and verifies that only the persisted earlier completion is deduplicated while the later live completion remains.

## Replay-gated replacement recovery and occurrence-aligned hydration

### Closed-child recovery preserves existing Temporal command histories

The three new recovery entry points now have independent Temporal patches:

- Initial follow-up signaling discovers a closed child.
- Completion signaling discovers a closed child.
- A stale acknowledgement retry discovers a closed child.

Existing histories without the matching patch retain the previous behavior and command sequence: the acknowledgement slot remains armed and no queue mutation or persistence activity is scheduled during replay.

New histories record the patch before they recover the closed sandbox, restore unacknowledged messages, persist the queue, and prepare a replacement sandbox.

The parameterized regression covers historical closed-child failures in all three paths and verifies that recovery commands are not introduced when the patch is absent.

### Every pending steer is normalized at a sandbox boundary

Closed-child and shutdown recovery now clear `steer` on the complete pending external queue, not only the message that was in flight.

If `S1` discovers the child is closed while `S2` is still unsent, both messages cross the boundary as ordered normal follow-ups. The replacement sandbox cannot merge `S2` into `S1`'s new turn.

The regression verifies that an in-flight steer and an unsent steer are signaled to the replacement child as two normal follow-ups in their original arrival order.

### Replacement recovery has deterministic backoff and a failure budget

Task management tracks consecutive sandbox replacements that fail before any follow-up is acknowledged.

- Replacement delays use deterministic exponential backoff: 1, 2, 4, 8 seconds, capped at 30 seconds.
- After five consecutive failures, the workflow stops starting replacement sandboxes and fails with the persisted follow-up queue still parked.
- The counter resets only after the child acknowledges an accepted normal follow-up or steer.

The behavior is protected by its own Temporal patch so existing histories retain their recorded timing commands.

Regressions cover the deterministic delay, the maximum-attempt boundary, the parked queue, and reset after acknowledged delivery.

### Repeated prompt identities reconcile by occurrence

Resume reconciliation no longer assigns every matching JSON-RPC prompt to the oldest hydrated turn with the same serialized request.

Hydrated and live events are split into ordered prompt occurrences, with task-run markers used when available. Matching proceeds from the newest suffix toward the oldest history, so a leaf turn whose request ID and prompt content repeat an ancestor turn binds to the latest occurrence.

Authoritative final-response versus inherited-chunk reconciliation is applied only within that matched occurrence. An ancestor final response or completion cannot suppress the current turn's chunk or completion.

### Promptless and partial live tails preserve unmatched events

Promptless live tails align with the latest hydrated turn that actually overlaps them.

Exact duplicate events are matched from the end of the turn. A live-only event does not advance or consume the hydrated cursor, so later persisted final responses and completions can still be recognized and removed without duplicating them.

The combined regression covers:

- Two identical prompt requests across ancestor and leaf turns.
- A current response chunk that must not be suppressed by the ancestor final response.
- Identical completion payloads where the current completion must survive.
- A promptless overlapping tail whose persisted final response and completion must be removed.
- A live-only event before those duplicates that must remain present.

## Replacement budget persistence and leaf-tail hydration scope

### Replacement exhaustion persists the complete pending queue

New task-management histories persist the current in-memory follow-up queue before failing at the five-attempt sandbox replacement boundary.

This includes messages that arrived after the last successful queue snapshot. The workflow raises only after persistence succeeds. If persistence fails, it keeps the queue in memory, waits with the existing deterministic backoff, and continues replacement recovery instead of claiming the messages are safely parked.

The behavior is selected with a Temporal patch so existing histories retain their recorded command sequence. Regressions cover both replay paths and the persistence-failure recovery path.

### Accepted acknowledgements reset the replacement failure budget first

Closed-child recovery now reconciles accepted follow-up and steer acknowledgements before it counts the current replacement failure.

If follow-up A was accepted but its acknowledgement was still queued when follow-up B discovers the closed child, A resets the consecutive failure counter. B then becomes the first failure in the new sequence instead of incorrectly exhausting the previous budget.

This ordering change is independently replay-gated. The regression verifies that four prior failures become one after acknowledged progress and the current closed-child recovery.

### Promptless live tails cannot align with an ancestor turn

Promptless live events are reconciled only against the immediate remaining hydrated suffix turn. They never search backward across earlier prompt or run occurrences for an identical completion or response payload.

Repeated prompt occurrences are pre-indexed by prompt identity and task run. Event keys are cached once per turn. Prompt-bearing lookup is logarithmic in the number of matching occurrences, while promptless reconciliation inspects only one scoped candidate.

The regression covers hydrated ancestor prompt and completion followed by the current prompt, with a live promptless completion identical to the ancestor. The current completion remains present and the current prompt can terminalize normally.

## Automated validation

Latest validation:

- Backend `process_task` workflow suite: 48 passed.
- Backend `execute_sandbox` workflow suite: 62 passed.
- Backend `task_management` workflow suite: 74 passed.
- Backend `task_management` activity suite: 16 passed.
- Focused PostHog Code session host suite: 143 passed.
- PostHog Code UI suite: 1,524 passed across 172 files.
- PostHog Code `@posthog/core` and `@posthog/ui` typechecks passed.
- Ruff, Python compilation, Biome, and diff checks passed for the changed files.

## Live cloud E2E validation

The running local backend and PostHog Code desktop app were tested after a full Electron main-process restart.

- Fresh Codex cloud run: one prompt and one `STEERFIX716A` reply.
- Active follow-up steering: the long-running queued prompt appeared once without its requested reply; the accepted `ACTIVESTEER716` steer appeared once and replied once in the same active turn.
- Queue mode fallback: one prompt and one `QUEUE716` reply.
- Real resume: the original run was terminalized before sending the next prompt, producing a new run that replied once with `RESUME716`.
- Cold restart and reopen: `Restored sandbox` appeared once; every tested prompt/reply pair remained in order with no duplicates, error state, pending prompt, or stale Thinking state.
- Cursor domains remained separate after cold hydration: the leaf-local `processedLineCount` was 54 while the full `cloudTranscriptEntryCount` was 191.
- Core and UI TypeScript package typechecks passed.
- Ruff, Python compilation, Biome formatting and lint, and diff checks passed.

Earlier validation across the branch also covered the full UI and agent packages, OpenAPI generation, Python compilation, shared and agent typechecks, and the focused Temporal, activity, client, adapter, and app-server suites.

## Live cloud-run verification

### Replacement budget and promptless leaf completion verification

- Task: `0c1eaa63-7484-424f-a762-892bae079b3c`
- Initial run: `659505ac-0cad-47d0-a2f1-a3f654b78e1a`
- Resumed run: `38facbda-5833-493d-a272-7b977bb21dd1`

The current backend and PostHog Code working trees ran through the configured backend and LLM gateway tunnels after a full Electron main-process restart.

Verified:

- The baseline Codex turn completed normally.
- A queued follow-up started `sleep 40`. While it was active, the cloud control switched to Steer and accepted `E2E716STEERED` into the same turn.
- The accepted steer returned exactly once, the superseded long-turn instruction produced no requested response, and the run had no terminal error or pending prompt.
- The initial workflow was terminalized before the next message. The next message created a distinct resumed run linked through `state.resume_from_run_id`.
- Before cold hydration, the resumed session was leaf-only with one restored-sandbox boundary and a complete current turn.
- After a full Electron restart and cold reopen, the transcript contained the complete initial and resumed history. The current promptless completion remained attached to the leaf turn instead of matching the ancestor completion.
- Semantic counts were stable: each completed prompt/reply marker appeared exactly twice, the superseded long-turn marker appeared only in its prompt, and `Restored sandbox` appeared once.
- The cold session had `processedLineCount=54`, `eventCount=167`, no pending prompt, no error, and a complete final turn.
- A new post-cold live follow-up returned `E2E716POSTCOLD` exactly twice. Its prompt and completion appended without a cursor gap or transcript replacement.
- Both database runs reached `completed`, and the resumed run pointed to the exact initial run.

The configured tunnels remained reachable throughout the run. The earlier tunnel URLs were stale, but `.env` already contained healthy replacements.

### Replay-gated recovery and repeated-prompt hydration verification

- Task: `415e7940-c11b-4db3-8a9e-663ee5109370`
- A run: `96674260-aab8-4ad6-8779-8119d24e4e10`
- B run: `0b64da48-0ff6-4822-9dc5-a030ae5065ce`
- C run: `258128b4-fd10-446f-ae12-3affb35b87aa`

The current backend and PostHog Code working trees ran through the active backend and LLM gateway tunnels.

Verified:

- A returned `BASE716REPLAY` once for the prompt and once for the response.
- A normal follow-up started a 120-second terminal command. `ACTIVESTEER716REPLAY` appeared as a user message while the command was still active and returned exactly once after the tool boundary.
- The superseded `LONG3716REPLAY` instruction remained exactly once as its user message and produced no response.
- Queue mode returned `QUEUE716REPLAY` exactly twice.
- A was terminalized before B was sent, and B returned `RESUME716REPLAY` exactly twice.
- After a full Electron restart, the complete A→B transcript loaded with one restored-sandbox boundary, no pending prompt, no error, and separate cursor domains: `processedLineCount=54` and `cloudTranscriptEntryCount=225`.
- B was terminalized before C was sent. C used the exact same `Reply with only BASE716REPLAY` prompt text as A after the new sandbox started.
- Before and after a second full Electron restart, `BASE716REPLAY` appeared exactly four times: the A and C prompt/response pairs. The latest repeated turn's response and completion were retained.
- The final cold transcript retained `ACTIVESTEER716REPLAY` and `QUEUE716REPLAY` exactly twice, `LONG3716REPLAY` exactly once, `RESUME716REPLAY` exactly twice, and two restored-sandbox boundaries.
- The final cold session had no pending prompt or error, its final turn was complete, and its leaf/full counters remained separate at `processedLineCount=54` and `cloudTranscriptEntryCount=284`.
- A new post-restart live follow-up returned `POSTCOLD716REPLAY` exactly twice, proving that live events still append after the occurrence-aligned hydration.
- Read-only database state confirmed the exact A→B→C `state.resume_from_run_id` chain, and all three runs reached `completed`.

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
