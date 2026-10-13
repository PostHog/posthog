/**
 * Hooks for the generated `logs-patterns` tool. A whole patterns response can hold 200 groups
 * with long templates and many members, which is more than an agent context holds. The hook
 * sends a default `limit` when the agent sets none, so the agent gets the top groups whole.
 */
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

export const DEFAULT_PATTERNS_LIMIT = 15

type PatternsParams = {
    query?: { limit?: number | null; [key: string]: unknown }
    [key: string]: unknown
}

function beforeRequest<T extends PatternsParams>(_context: Context, params: T): T {
    if (params.query?.limit != null) {
        return params
    }
    return { ...params, query: { ...params.query, limit: DEFAULT_PATTERNS_LIMIT } }
}

export default { beforeRequest } satisfies ToolHooks<PatternsParams>
