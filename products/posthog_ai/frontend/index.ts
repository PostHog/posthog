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
// `SandboxRunViewer` is the prepackaged default layout for the common embed (tasks, signals inbox).
export { RunViewer, SandboxRunViewer } from './components/SandboxRunViewer'
export type { RunViewerRootProps, SandboxRunViewerProps } from './components/SandboxRunViewer'
export { SandboxComposer } from './components/SandboxComposer'
export type { SandboxComposerProps } from './components/SandboxComposer'

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
// `SandboxThreadView` is the prepackaged virtualized presenter (also `Thread.Root`).
export { Thread } from './components/Thread'
export { SandboxThreadView } from './components/SandboxThreadView'
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
export { SandboxActivity } from './components/SandboxActivity'

// --- Tool rendering + registry ---
export { sandboxToolRegistry, lookupSandboxToolRenderer } from './components/tool/sandboxToolRegistry'
export type {
    SandboxToolRendererProps,
    SandboxToolRegistryEntry,
    SandboxToolRegistry,
} from './components/tool/sandboxToolRegistry'
export { GenericMcpToolRenderer } from './components/tool/GenericMcpToolRenderer'
export { SandboxDataToolRow } from './components/tool/SandboxDataToolRow'
export { SandboxToolActivity } from './components/tool/SandboxToolActivity'
export type { SandboxToolActivityProps } from './components/tool/SandboxToolActivity'
export { SandboxFilePath } from './components/tool/SandboxFilePath'
export { findAllDiffContent, getDiffStats, languageFromPath } from './components/tool/toolDiffContent'
export type { ToolCallDiffContent } from './components/tool/toolDiffContent'

// --- Questions / multi-field forms ---
export { QuestionField, MultiFieldQuestion, isFieldValid } from './components/QuestionField'
export { OptionSelector } from './components/OptionSelector'
export type { Option } from './components/OptionSelector'

// --- Stream logic + interaction facade ---
export { sandboxStreamLogic, isTerminalRunStatus, SANDBOX_INITIAL_PERMISSION_MODE } from './logics/sandboxStreamLogic'
export type { SandboxStreamLogicProps, SandboxSseStatus, SandboxRunStatus } from './logics/sandboxStreamLogic'
export { taskRunInteractionLogic } from './logics/taskRunInteractionLogic'
export type { TaskRunInteractionLogicProps, QueuedMessage } from './logics/taskRunInteractionLogic'

// --- Permission / question / resource surfaces ---
export { SandboxPermissionInput } from './components/SandboxPermissionInput'
export { SandboxQuestionInput } from './components/SandboxQuestionInput'
export { SandboxResourcesBar } from './components/SandboxResourcesBar'
export { SandboxContextUsage } from './components/SandboxContextUsage'

// --- Thinking-message helpers ---
export { getThinkingMessageFromResponse, getRandomThinkingMessage, THINKING_MESSAGES } from './utils/thinkingMessages'

// --- Types ---
export type {
    ThreadItem,
    ToolInvocation,
    PermissionRequestRecord,
    ContextUsage,
    RunArtifacts,
    SandboxProgressStep,
} from './types/sandboxStreamTypes'
export type { SandboxToolCallMessage } from './types/sandboxToolTypes'
