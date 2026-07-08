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

// --- Thinking-message helpers ---
export { getThinkingMessageFromResponse, getRandomThinkingMessage, THINKING_MESSAGES } from '../utils/thinkingMessages'

// --- Composer model/effort helpers (pure — no component imports) ---
export { resolveEffortForModel, DEFAULT_COMPOSER_MODEL, DEFAULT_COMPOSER_EFFORT } from '../utils/composerModels'

// --- Attached-context store + injection hook (headless) ---
// Global registry of on-screen context providers; `contextItems` is what the send paths wrap into a
// `<posthog_context>` block. `useAttachedContext` registers a provider for the lifetime of a mount.
export { attachedContextLogic } from '../logics/attachedContextLogic'
export { useAttachedContext } from '../hooks/useAttachedContext'
export type { UseAttachedContextOptions } from '../hooks/useAttachedContext'
export { attachedContextItemKey } from '../types/contextTypes'

// --- User-picked context (the composer's @-affordance, headless half) ---
// `contextPickerLogic` owns explicit user picks and registers them as the `user-picker` provider;
// the `AttachedContextBar` component (Tier 2 `api/primitives`) is its prepackaged UI.
export { contextPickerLogic, taxonomicItemToAttachedContext, PICKER_PROVIDER_ID } from '../logics/contextPickerLogic'
export type { PickableTaxonomicItem } from '../logics/contextPickerLogic'

// --- Tool-stream event bus + subscription hook (headless) ---
// `runStreamLogic` publishes tool-call lifecycle events (resolved names) plus turn-complete and
// run-terminal events; subscribe to react when the agent invokes a specific tool.
// `useToolStreamListener` registers a subscription for a mount's life.
export { toolStreamEventsLogic } from '../logics/toolStreamEventsLogic'
export type { ToolStreamSubscription } from '../logics/toolStreamEventsLogic'
export { useToolStreamListener } from '../hooks/useToolStream'
export type { UseToolStreamListenerOptions } from '../hooks/useToolStream'

// --- Foreground stream registry + MCP tool apply-back (headless) ---
// `foregroundStreamLogic` marks the single stream rendered in the side panel the user is watching; a
// surface registers via `useForegroundStream`. `useMcpToolApplyBack` reacts to that foreground run's
// MCP tool calls (foreground-gated, replay-excluded) so a scene can apply a generated query back when
// its tool completes or at the end of the turn.
export { foregroundStreamLogic } from '../logics/foregroundStreamLogic'
export { useForegroundStream } from '../hooks/useForegroundStream'
export { useMcpToolApplyBack } from '../hooks/useMcpToolApplyBack'
export type { ApplyOn, McpToolApplyContext, UseMcpToolApplyBackOptions } from '../hooks/useMcpToolApplyBack'

// --- Panel view state (headless) ---
// Panel-level view state (active run vs. history vs. composer) for hosts that render chrome — e.g. a
// header back button — outside the lazy panel chunk (Tier 1 `api/runner`).
export { runnerPanelLogic } from '../logics/runnerPanelLogic'
export type { RunnerPanelLogicProps, ActiveCreation } from '../logics/runnerPanelLogic'

// --- Composer seed hand-off (headless) ---
// A one-shot store that lets a host seed a not-yet-mounted composer with an initial prompt (optionally
// auto-submitting it); the paired `taskTrackerSceneLogic` consumes it on mount or when it arrives.
export { composerSeedLogic } from '../logics/composerSeedLogic'
export type { ComposerSeed, ComposerSeedLogicProps } from '../logics/composerSeedLogic'
