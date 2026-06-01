/**
 * Hand-rolled mirror of `McpRefSchema` from `@posthog/agent-shared`. Kept
 * here (rather than imported) to avoid pulling the agent-shared workspace
 * into the console's bundle; the schema is small + stable enough that a
 * local mirror is cheaper than the cross-workspace dep.
 *
 * Migration intent: once the runtime-mcps spec flattens to a single shape
 * (see `docs/agent-platform/plans/runtime-mcps.md` "Future migration"),
 * drop the discriminated union here too.
 */

export interface AgentMcpRef {
    kind: 'agent'
    slug: string
}

export interface ExternalMcpRef {
    kind: 'external'
    id: string
    url: string
    auth?: { integration?: string }
    secrets?: string[]
    allowlist?: string[]
}

export type McpRef = AgentMcpRef | ExternalMcpRef
