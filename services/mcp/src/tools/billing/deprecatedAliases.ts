import { z } from 'zod'

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

// The old tools paged with page_size and after. The time-series tools take the same values as limit and cursor.
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

/** Old billing tool name → alias factory, spread into TOOL_MAP. */
export const BILLING_DEPRECATED_ALIASES: Record<string, () => ToolBase<ZodObjectAny>> = Object.fromEntries(
    Object.entries(REPLACEMENTS).map(([oldName, newName]) => [oldName, makeAlias(oldName, newName)])
)
