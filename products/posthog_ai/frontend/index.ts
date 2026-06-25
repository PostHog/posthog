// Public component API of the PostHog AI agent-run surface — the conversation-agnostic agent UI.
// Every external consumer (tasks, the signals inbox, and the Max scene in scenes/max) imports from
// THIS barrel, never from deep subtree paths, so the internal layout can move without touching them.
//
// Coupling boundary: this surface couples to the tasks run API (`products/tasks/frontend/generated/api`)
// by design — task + taskrun + streaming together ARE the surface. It must never import the conversations
// API or Max conversation orchestration (`scenes/max/*`, `maxThreadLogic`, `maxContextLogic`, `MaxUIContext`):
// Max is a consumer of this surface, not a dependency of it.

// --- Embeddable run surface ---
// `RunViewer` is the Radix-style compound (Root + Thread/Prompt/Composer/Resources/ContextUsage slots);
// called directly (`<RunViewer .../>`) it renders the prepackaged default layout for the common embed.
export { RunViewer } from './components/RunViewer'
export type { RunViewerRootProps, RunViewerProps } from './components/RunViewer'
export { RunComposer } from './components/RunComposer'
export type { RunComposerProps } from './components/RunComposer'

// --- Composer (Radix-style compound) ---
export { Composer } from './components/composer/Composer'
export type {
    ComposerRootProps,
    ComposerFrameProps,
    ComposerTextareaProps,
    ComposerSubmitProps,
} from './components/composer/Composer'

// --- Thread + message presenters ---
// `Thread` is the Radix-style compound (Root + Message/Markdown/Reasoning/Failure/Activity/ToolCall atoms);
// `ThreadView` is the prepackaged virtualized presenter (also `Thread.Root`).
export { Thread } from './components/Thread'
export { ThreadView } from './components/ThreadView'
export { MessageTemplate } from './messages/MessageTemplate'
export { MarkdownMessage } from './messages/MarkdownMessage'
export { ReasoningAnswer } from './messages/ReasoningAnswer'
export type { ReasoningAnswerProps } from './messages/ReasoningAnswer'
export { AssistantFailureMessage } from './messages/AssistantFailureMessage'

// --- Activity primitives ---
export {
    Activity,
    ActivityDetails,
    ActivityHeader,
    ActivityStatusIcon,
    ActivitySubsteps,
    ActivityToggleSection,
    ShimmeringContent,
} from './components/ActivityPrimitives'
export type { ActivityStatus } from './components/ActivityPrimitives'
export { RunActivity } from './components/RunActivity'

// --- Tool rendering + registry ---
export { toolRegistry, lookupToolRenderer } from './components/tool/toolRegistry'
export type { ToolRendererProps, ToolRegistryEntry, ToolRegistry } from './components/tool/toolRegistry'
export { GenericMcpToolRenderer } from './components/tool/GenericMcpToolRenderer'
export { DataToolRow } from './components/tool/DataToolRow'
export { ToolActivity } from './components/tool/ToolActivity'
export type { ToolActivityProps } from './components/tool/ToolActivity'
export { FilePath } from './components/tool/FilePath'
export { findAllDiffContent, getDiffStats, languageFromPath } from './components/tool/toolDiffContent'
export type { ToolCallDiffContent } from './components/tool/toolDiffContent'

// --- Questions / multi-field forms ---
export { QuestionField, MultiFieldQuestion, isFieldValid } from './components/QuestionField'
export { OptionSelector } from './components/OptionSelector'
export type { Option } from './components/OptionSelector'

// --- Stream logic + interaction facade ---
export { runStreamLogic, isTerminalRunStatus, INITIAL_PERMISSION_MODE } from './logics/runStreamLogic'
export type { RunStreamLogicProps, RunSseStatus, RunStatus } from './logics/runStreamLogic'
export { runInteractionLogic } from './logics/runInteractionLogic'
export type { RunInteractionLogicProps, QueuedMessage } from './logics/runInteractionLogic'

// --- Permission / question / resource surfaces ---
export { PermissionInput } from './components/PermissionInput'
export { QuestionInput } from './components/QuestionInput'
export { ResourcesBar } from './components/ResourcesBar'
export { ContextUsageBar } from './components/ContextUsageBar'

// --- Thinking-message helpers ---
export { getThinkingMessageFromResponse, getRandomThinkingMessage, THINKING_MESSAGES } from './utils/thinkingMessages'

// --- Types ---
export type {
    ThreadItem,
    ToolInvocation,
    PermissionRequestRecord,
    ContextUsage,
    RunArtifacts,
    ProgressStep,
} from './types/streamTypes'
export type { ToolCallMessage } from './types/toolTypes'
