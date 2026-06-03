/**
 * Hand-rolled mirror of `McpRefSchema` from `@posthog/agent-shared`. Kept
 * here (rather than imported) to avoid pulling the agent-shared workspace
 * into the console's bundle; the schema is small + stable enough that a
 * local mirror is cheaper than the cross-workspace dep.
 */

/**
 * Per-tool entry inside `McpRef.tools[]`. Bare string is the
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

export interface McpRef {
    id: string
    url: string
    auth?: { integration?: string }
    secrets?: string[]
    /** Replaces the legacy `allowlist?: string[]`. See `McpToolEntry`. */
    tools?: McpToolEntry[]
}
