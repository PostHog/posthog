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

/**
 * Per-tool entry inside `ExternalMcpRef.tools[]`. Bare string is the
 * inclusion-only case (was `allowlist[]` pre-PR-7); object form adds
 * `requires_approval` + `approval_policy`. Approval shape is intentionally
 * kept loose here — the console only renders the count + flags; the runner
 * is authoritative for policy validation.
 */
export type McpToolEntry =
    | string
    | {
          name: string
          requires_approval?: boolean
          approval_policy?: Record<string, unknown>
      }

export interface ExternalMcpRef {
    kind: 'external'
    id: string
    url: string
    auth?: { integration?: string }
    secrets?: string[]
    /** Replaces the legacy `allowlist?: string[]`. See `McpToolEntry`. */
    tools?: McpToolEntry[]
}

export type McpRef = AgentMcpRef | ExternalMcpRef
