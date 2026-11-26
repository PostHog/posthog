import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/billing'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

/**
 * Deprecation aliases for the billing tools that read /api/billing/, which takes the organization from the user's
 * current project. Each old name forwards its arguments to the time-series tool that reads the same series from
 * /api/organizations/:organization_id/billing/, and annotates the response so agents learn the new name. Remove this
 * file, its TOOL_MAP registration and the matching `tool-definitions.json` entries once callers have moved.
 */
const REPLACEMENTS: Record<string, string> = {
    'billing-usage-get': 'billing-usage-timeseries-get',
    'billing-spend-get': 'billing-spend-timeseries-get',
}

function makeAlias(oldName: string, newName: string): () => ToolBase<ZodObjectAny> {
    return (): ToolBase<ZodObjectAny> => {
        const inner = GENERATED_TOOLS[newName]!()
        return {
            ...inner,
            name: oldName,
            handler: async (context: Context, params: z.infer<ZodObjectAny>) => {
                const result = await inner.handler(context, params)
                return {
                    ...(result as object),
                    _deprecation_notice: `${oldName} is deprecated. Call ${newName} directly next time, with the same arguments. This alias will be removed.`,
                }
            },
        }
    }
}

/** Old billing tool name → alias factory, spread into TOOL_MAP. */
export const BILLING_DEPRECATED_ALIASES: Record<string, () => ToolBase<ZodObjectAny>> = Object.fromEntries(
    Object.entries(REPLACEMENTS).map(([oldName, newName]) => [oldName, makeAlias(oldName, newName)])
)
