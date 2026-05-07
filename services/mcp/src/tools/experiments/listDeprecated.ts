import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Deprecation alias for the renamed `experiment-list` tool. Forwards arguments
 * to the current handler and annotates the response so agents discover the new
 * name without the call failing. Remove once callers have migrated.
 */
const experimentListDeprecated = (): ToolBase<ZodObjectAny> => {
    const inner = GENERATED_TOOLS['experiment-list']!()
    return {
        ...inner,
        name: 'experiment-get-all',
        handler: async (context: Context, params: z.infer<ZodObjectAny>) => {
            const result = await inner.handler(context, params)
            return {
                ...(result as object),
                _deprecation_notice:
                    'experiment-get-all has been renamed to experiment-list. Call experiment-list directly next time — this alias will be removed.',
            }
        },
    }
}

export default experimentListDeprecated
