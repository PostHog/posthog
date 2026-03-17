import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { LLMAnalyticsGetCostsSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = LLMAnalyticsGetCostsSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<{ results: unknown[] }>

export const getLLMCostsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { projectId, days } = params

    const trendsQuery = {
        kind: 'TrendsQuery',
        dateRange: {
            date_from: `-${days || 6}d`,
            date_to: null,
        },
        filterTestAccounts: true,
        series: [
            {
                event: '$ai_generation',
                name: '$ai_generation',
                math: 'sum',
                math_property: '$ai_total_cost_usd',
                kind: 'EventsNode',
            },
        ],
        breakdownFilter: {
            breakdown_type: 'event',
            breakdown: '$ai_model',
        },
    }

    const costsResult = await context.api.query({ projectId: String(projectId) }).execute({ queryBody: trendsQuery })
    if (!costsResult.success) {
        throw new Error(`Failed to get LLM costs: ${costsResult.error.message}`)
    }
    return withPostHogUrl(
        { results: costsResult.data.results },
        `${context.api.getProjectBaseUrl(String(projectId))}/llm-observability`
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('llm-costs', {
        name: 'get-llm-total-costs-for-project',
        schema,
        handler: getLLMCostsHandler,
    })
