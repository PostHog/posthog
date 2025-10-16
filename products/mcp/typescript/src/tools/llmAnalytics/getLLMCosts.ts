import { LLMAnalyticsGetCostsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = LLMAnalyticsGetCostsSchema

type Params = z.infer<typeof schema>

export const getLLMCostsHandler = async (context: Context, params: Params) => {
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

    const costsResult = await context.api
        .query({ projectId: String(projectId) })
        .execute({ queryBody: trendsQuery })
    if (!costsResult.success) {
        throw new Error(`Failed to get LLM costs: ${costsResult.error.message}`)
    }
    return {
        content: [{ type: 'text', text: JSON.stringify(costsResult.data.results) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'get-llm-total-costs-for-project',
    schema,
    handler: getLLMCostsHandler,
})

export default tool
