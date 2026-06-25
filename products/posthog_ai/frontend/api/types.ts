// Tier 3 — domain types (folded thread + tool shapes). Pure types: zero runtime, React, or registry
// imports, so this is the clean lane for status badges and automation that only need the shapes.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface — import from here, not from
// deep `../types/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export type {
    ThreadItem,
    ToolInvocation,
    PermissionRequestRecord,
    ContextUsage,
    RunArtifacts,
    ProgressStep,
} from '../types/streamTypes'
export type { ToolCallMessage } from '../types/toolTypes'
