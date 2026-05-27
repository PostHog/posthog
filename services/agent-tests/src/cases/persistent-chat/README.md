# Persistent multi-turn chat — e2e spec

These suites pin the behaviour we want from the chat-shaped agent path.
They are **`describe.skip`'d on purpose** — the feature isn't built yet.
Each test documents the contract we'll implement against. Remove the
`.skip` as we land each capability and the tests should pass.

## What's missing today (see `docs/persistent-chat.md` once written)

`AssServerExecutor` runs the SDK in a single `query()` to completion
and parks the agent on an in-process Promise via `ask_for_input`. The
Redis bus carries `/send` messages but they're dropped unless that
Promise is currently pending. The `SessionState` shape (messages,
pendingInputs, turnCount) and the worker's `awaiting_input` /
`tool_call` branches exist but aren't reached.

## Coverage matrix

| File                                | Cases | What it pins                                                       |
| ----------------------------------- | ----- | ------------------------------------------------------------------ |
| `basic-multi-turn.test.ts`          | 1     | Two-turn conversation over `/send`; state persists in DB           |
| `queued-followups.test.ts`          | 2, 3  | `/send` mid-turn → queued in `pendingInputs`, drained next turn    |
| `worker-resume.test.ts`             | 4     | Worker dies between turns; new worker resumes from persisted state |
| `slack-thread-continuation.test.ts` | 5     | Second mention in same `thread_ts` continues the existing session  |
| `lifecycle-edges.test.ts`           | 6, 7  | `/cancel` a parked session; `/send` to a completed session → 410   |

## Why these run against the shared cluster

These are isolated tests — they use the `router` test executor and
its stub kinds. We add a new kind for these cases: `chat-echo`, which
echoes the latest user message into the assistant reply and returns
`awaiting_input` after each turn. That's enough to verify the turn
boundary + state plumbing without spending Anthropic credits.

Tests gated on real Claude (multi-turn coherence over real text) live
under `apps/` and stay separate.
