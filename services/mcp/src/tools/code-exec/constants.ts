/**
 * Feature flag gating the code-execution exec verbs (`run` / `apply` / `types`).
 * Kept in its own module so the request-state resolver can join it into the batched flag evaluation
 * without importing the runtime — which pulls in the generated discovery index
 * and the sandbox executor.
 */
export const CODE_EXECUTION_FEATURE_FLAG = 'mcp-code-execution'
