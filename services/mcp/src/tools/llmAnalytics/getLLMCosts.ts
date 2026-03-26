import type { z } from 'zod'

import { LLM_COSTS_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { LLMAnalyticsGetCostsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = LLMAnalyticsGetCostsSchema

type Params = z.infer<typeof schema>

export const getLLMCostsHandler: ToolBase<typeof schema, unknown>['handler'] = async (
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
    return {
        results: costsResult.data.results,
        _posthogUrl: `${context.api.getProjectBaseUrl(String(projectId))}/llm-observability`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'get-llm-total-costs-for-project',
    schema,
    handler: getLLMCostsHandler,
    _meta: {
        ui: {
            resourceUri: LLM_COSTS_RESOURCE_URI,
        },
    },
})

export default tool
