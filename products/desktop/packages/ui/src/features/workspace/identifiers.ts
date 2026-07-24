/**
 * Shared TanStack Query partial-filter key for the workspace map. The UI read
 * hooks own this query (`trpc.workspace.getAll`); every host invalidator
 * (create/delete/focus/etc.) matches against this key so the workspace UI stays
 * in sync. tRPC registers the query under `[["workspace", "getAll"], { type }]`,
 * so the path must be wrapped in an outer array to partial-match it — a flat
 * `["workspace", "getAll"]` matches nothing.
 */
export const WORKSPACE_QUERY_KEY = [["workspace", "getAll"]] as const;
