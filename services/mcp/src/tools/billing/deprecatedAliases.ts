import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/billing'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

// The old names read /api/billing/, which follows the user's current project. Remove this file, its TOOL_MAP entry
// and its `tool-definitions.json` entries once callers have moved to the time-series tools.
const REPLACEMENTS: Record<string, string> = {
    'billing-usage-get': 'billing-usage-timeseries-get',
    'billing-spend-get': 'billing-spend-timeseries-get',
}

const LEGACY_PAGINATION = {
    page_size: z
        .number()
        .int()
        .min(1)
        .max(1000)
        .nullish()
        .describe('Deprecated name for `limit`: series per page, ranked by total. Requires a project breakdown.'),
    after: z
        .string()
        .max(512)
        .nullish()
        .describe("Deprecated name for `cursor`: the cursor from the previous page's `next` link."),
}

function translatePagination(params: Record<string, unknown>): Record<string, unknown> {
    const { page_size, after, ...forwarded } = params
    if (forwarded.limit == null && page_size != null) {
        forwarded.limit = page_size
    }
    if (forwarded.cursor == null && after != null) {
        forwarded.cursor = after
    }
    return forwarded
}

function makeAlias(oldName: string, newName: string): () => ToolBase<ZodObjectAny> {
    return (): ToolBase<ZodObjectAny> => {
        const inner = GENERATED_TOOLS[newName]!()
        return {
            ...inner,
            name: oldName,
            schema: (inner.schema as z.ZodObject<z.ZodRawShape>).extend(LEGACY_PAGINATION),
            handler: async (context: Context, params: z.infer<ZodObjectAny>) => {
                const result = await inner.handler(context, translatePagination(params))
                // Spreading the result would drop the non-enumerable markers that fence project names as data, so
                // the notice goes onto the same object.
                Object.defineProperty(result, '_deprecation_notice', {
                    value: `${oldName} is deprecated. Call ${newName} directly next time, with limit and cursor in place of page_size and after. This alias will be removed.`,
                    enumerable: true,
                })
                return result
            },
        }
    }
}

export const BILLING_DEPRECATED_ALIASES: Record<string, () => ToolBase<ZodObjectAny>> = Object.fromEntries(
    Object.entries(REPLACEMENTS).map(([oldName, newName]) => [oldName, makeAlias(oldName, newName)])
)
