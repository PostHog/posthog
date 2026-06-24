// Public run surface of the sandbox renderer — the conversation-agnostic PostHog AI agent-run UI.
// Tasks and the signals inbox consume this barrel (`SandboxRunViewer`, `SandboxComposer`, the logic,
// and the types), never deep paths. PostHog AI (scenes/max) additionally composes lower-level
// primitives from the subtree directly, by design. This module talks to tasks only via `api.tasks.*`
// / `products/tasks/frontend/generated/api` and must never import the conversations API or Max
// conversation orchestration.

export { SandboxRunViewer } from './components/SandboxRunViewer'
export type { SandboxRunViewerProps } from './components/SandboxRunViewer'
export { SandboxComposer } from './components/SandboxComposer'
export type { SandboxComposerProps } from './components/SandboxComposer'
export { Composer } from './components/composer/Composer'
export type {
    ComposerRootProps,
    ComposerFrameProps,
    ComposerTextareaProps,
    ComposerSubmitProps,
} from './components/composer/Composer'
export { SandboxThreadView } from './components/SandboxThreadView'

export { sandboxStreamLogic, isTerminalRunStatus, SANDBOX_INITIAL_PERMISSION_MODE } from './sandboxStreamLogic'
export type { SandboxStreamLogicProps, SandboxSseStatus, SandboxRunStatus } from './sandboxStreamLogic'

export { taskRunInteractionLogic } from './taskRunInteractionLogic'
export type { TaskRunInteractionLogicProps, QueuedMessage } from './taskRunInteractionLogic'

export { SandboxPermissionInput } from './components/SandboxPermissionInput'
export { SandboxQuestionInput } from './components/SandboxQuestionInput'
export { SandboxResourcesBar } from './components/SandboxResourcesBar'
export { SandboxContextUsage } from './components/SandboxContextUsage'

export type {
    ThreadItem,
    ToolInvocation,
    PermissionRequestRecord,
    ContextUsage,
    RunArtifacts,
    SandboxProgressStep,
} from './types/sandboxStreamTypes'
export type { SandboxToolCallMessage } from './types/sandboxToolTypes'
