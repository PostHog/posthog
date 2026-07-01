export type {
    ThreadItem,
    ToolInvocation,
    ToolInvocationStatus,
    ToolStreamEvent,
    PermissionRequestRecord,
    ContextUsage,
    RunArtifacts,
    ProgressStep,
} from '../types/streamTypes'
export type { ToolCallMessage } from '../types/toolTypes'

// Context injection — the typed references a consumer attaches to a run (mirrors the backend
// `AttachedContext` contract). `agentContextKey` is a pure dedupe/chip-key helper.
export type { AgentContextItem, AgentContextItemType, AgentContextChip } from '../types/contextTypes'
export { agentContextKey } from '../types/contextTypes'

// Pure tool-key resolver — resolves a raw invocation to its registry key (the inner sub-tool for
// PostHog's single-exec MCP server). No registry import, so it stays off the side-effectful `api/tools`
// chunk; a subscriber can resolve keys to match a specific tool set without pulling the renderers.
export { resolveToolCall } from '../components/tool/toolResolver'
export type { ResolvedToolCall, ResolvableToolCall } from '../components/tool/toolResolver'
