import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/skills'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Matches DEFAULT_BODY_PAGE_LENGTH in products/skills/backend/api/skill_serializers.py.
 * The API applies it only when the caller omits body_length. An agent that sends a larger
 * body_length gets a slice that the MCP client can truncate in transit, and the API reports
 * body_next_offset as null for that slice. The agent then treats a cut-off body as complete.
 * This cap keeps every page small enough to arrive whole, so body_next_offset stays valid.
 */
export const MAX_SKILL_BODY_PAGE_LENGTH = 8000

export function skillGet(): ToolBase<ZodObjectAny> {
    const inner = GENERATED_TOOLS['skill-get']!()
    return {
        ...inner,
        handler: async (context: Context, params: z.infer<ZodObjectAny>) => {
            const requested = typeof params.body_length === 'number' ? params.body_length : MAX_SKILL_BODY_PAGE_LENGTH
            return inner.handler(context, {
                ...params,
                body_length: Math.min(requested, MAX_SKILL_BODY_PAGE_LENGTH),
            })
        },
    }
}
