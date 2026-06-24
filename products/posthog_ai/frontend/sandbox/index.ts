// Public surface of the sandbox renderer — the conversation-agnostic PostHog AI agent-run UI.
// PostHog AI (scenes/max), tasks, and the signals inbox consume this barrel, never deep paths.
// This module talks to tasks only via `api.tasks.*` / `products/tasks/frontend/generated/api`
// and must never import the conversations API or Max conversation orchestration.

export { SandboxRunViewer } from './components/SandboxRunViewer'
export type { SandboxRunViewerProps } from './components/SandboxRunViewer'
export { SandboxThreadView } from './components/SandboxThreadView'

export { sandboxStreamLogic, isTerminalRunStatus, SANDBOX_INITIAL_PERMISSION_MODE } from './sandboxStreamLogic'
export type { SandboxStreamLogicProps, SandboxSseStatus, SandboxRunStatus } from './sandboxStreamLogic'

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
