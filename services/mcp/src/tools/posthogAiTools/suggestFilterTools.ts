import type { z } from 'zod'

import {
    SuggestErrorTrackingFiltersSchema,
    SuggestRevenueAnalyticsFiltersSchema,
    SuggestSessionRecordingFiltersSchema,
    SuggestWebAnalyticsFiltersSchema,
} from '@/schema/tool-inputs'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

interface SuggestFiltersResult {
    status: 'sent_to_open_page'
    note: string
    filters: Record<string, unknown>
}

/**
 * The suggest-*-filters tools are schema-echoes reserved for the PostHog AI conversation sandbox
 * (gated by the `posthog_ai_frontend:read` scope). The MCP executor validates the payload against
 * the tool's zod schema before the handler runs, so the handler only echoes the validated filters
 * back and adds a short note. Nothing persists server-side; the PostHog AI browser side panel is
 * the real consumer and applies the returned filters to whichever scene the user has open.
 */
function makeSuggestFilterTool<TSchema extends ZodObjectAny>(
    name: string,
    schema: TSchema,
    pageLabel: string
): () => ToolBase<TSchema, SuggestFiltersResult> {
    return () => ({
        name,
        schema,
        handler: (_context: Context, params: z.infer<TSchema>): Promise<SuggestFiltersResult> =>
            Promise.resolve({
                status: 'sent_to_open_page',
                note:
                    `These filters have been sent to the ${pageLabel} page the user has open in the PostHog AI ` +
                    'side panel and applied there. The applied filter set is returned below.',
                filters: params as Record<string, unknown>,
            }),
    })
}

export const suggestWebAnalyticsFilters = makeSuggestFilterTool(
    'suggest-web-analytics-filters',
    SuggestWebAnalyticsFiltersSchema,
    'web analytics'
)

export const suggestRevenueAnalyticsFilters = makeSuggestFilterTool(
    'suggest-revenue-analytics-filters',
    SuggestRevenueAnalyticsFiltersSchema,
    'revenue analytics'
)

export const suggestErrorTrackingFilters = makeSuggestFilterTool(
    'suggest-error-tracking-filters',
    SuggestErrorTrackingFiltersSchema,
    'error tracking'
)

export const suggestSessionRecordingFilters = makeSuggestFilterTool(
    'suggest-session-recording-filters',
    SuggestSessionRecordingFiltersSchema,
    'session replay'
)
