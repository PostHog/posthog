# Adding AI E2E cases

Read [architecture.md](architecture.md) before changing the launcher, fixtures, controls, or CI job.

- Reuse the text and insight-update fixtures first. Store new model events as one provider event per NDJSON line under
  `fixtures/<provider>/`. The mock emits SSE; do not send NDJSON to an SDK.
- Declare sequences in ordinary TypeScript. Give messages and tool calls explicit synthetic IDs. Require the real tool
  result before declaring a response after a tool call.
- Choose the cheapest effective test layer. Put retry deadlines, exhaustion, error classification, cancellation, draft/answer
  preservation, and stale ownership in backend or Kea tests with fake clocks. Use a browser to prove visible recovery across
  the real application, Temporal, and sandbox boundaries.
- Select the fault matching the failure: `registration` for real Temporal NOT_FOUND, `worker` for queued processing, or
  `approval` for the exact upstream no-session rejection before execution. Keep controls outside workflow code.
- Arm the control, wait on `waitUntilReached` and any required observation barrier, assert the intermediate UI, release it,
  and assert the visible outcome. Never use sleeps or timing guesses. Every required fault must appear in the timeline.
- Assert persisted effects and their count for tools. A successful HTTP response alone is insufficient.
- Invent all prompts, resource names, and examples. Use `example.com` and temporary signing credentials. Never copy customer
  conversations, internal logs, or live tokens into fixtures or artifacts intended for publication.
- Preserve attempt ownership in every control and cleanup operation. Release outstanding barriers before teardown. Capture
  evidence before deleting resources. Never remove unrelated containers, workflows, or projects.
- Run commands from the repository root through `.codex/with-flox`. Start with a focused case at zero retries. Before calling
  browser coverage stable, run ten repetitions per case/runtime on the actual CI runner and record runtime and peak memory.
- Keep regular `run-surface.spec.ts` tests separate. They mock the task API and stream and are useful for cheap rendering
  coverage; they do not establish real Temporal or agent recovery.
