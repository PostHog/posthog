// Tier 3 — headless stream + interaction logic and thinking-message helpers. Imports only from
// ../logics/* and ../utils/* (no component or registry imports), so it never pulls the side-effectful
// tool registry or the markdown/virtualization chunks. Pair with ./types for a fully headless lane —
// status badges, automation, or a consumer that drives a run without rendering the prepackaged UI.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../logics/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

// --- Stream logic + status helpers ---
// `runStreamLogic` keys on a generic `streamKey` (conversation id for Max, run/task id for a task
// viewer); read `currentRunStatus` / `isTerminalRunStatus` off it for a status badge with no UI.
export { runStreamLogic, isTerminalRunStatus, INITIAL_PERMISSION_MODE } from '../logics/runStreamLogic'
export type { RunStreamLogicProps, RunSseStatus, RunStatus } from '../logics/runStreamLogic'

// --- Interaction facade (follow-up / queue) ---
export { runInteractionLogic } from '../logics/runInteractionLogic'
export type { RunInteractionLogicProps, QueuedMessage } from '../logics/runInteractionLogic'

// --- Context store (frontend context injection) ---
// Multi-source store keyed by `streamKey`; `attachedContext` is what a send path forwards. Populate it
// with the React bindings in ./context, or drive it directly from another logic.
export { runContextLogic } from '../logics/runContextLogic'
export type { RunContextLogicProps } from '../logics/runContextLogic'

// --- Tool-stream selectors (non-React tool subscription) ---
// Selector view over streamed tool invocations, keyed by resolved key / raw name. For a component,
// prefer the `useToolStream` hook in ./context.
export { toolStreamLogic } from '../logics/toolStreamLogic'
export type { ToolStreamLogicProps, ResolvedInvocation } from '../logics/toolStreamLogic'

// --- Thinking-message helpers ---
export { getThinkingMessageFromResponse, getRandomThinkingMessage, THINKING_MESSAGES } from '../utils/thinkingMessages'
