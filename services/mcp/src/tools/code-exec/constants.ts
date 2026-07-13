/**
 * Feature flags for the code-execution surface. Kept in their own module so the
 * request-state resolver can join them into the batched flag evaluation
 * without importing the runtime — which pulls in the generated discovery index
 * and the sandbox executor.
 */

/** Gates the code-execution exec verbs (`run` / `apply` / `types` / `sql`). */
export const CODE_EXECUTION_FEATURE_FLAG = 'mcp-code-execution'

/**
 * Gates the code-first exec surface (spec §4.3/§4.6 Phase 3): legacy verbs go
 * hidden with deprecation footers and `info`/`schema`/`search` alias to `types`.
 * Independent of `CODE_EXECUTION_FEATURE_FLAG` so the instruction flip can
 * trail the runtime, but inert without it — the aliases need the discovery
 * index the runtime carries.
 */
export const CODE_FIRST_FEATURE_FLAG = 'mcp-code-first'
