import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    evaluationId: z
        .string()
        .uuid()
        .optional()
        .describe('Filter results by evaluation UUID. Provide this or generationId (or both).'),
    generationId: z
        .string()
        .uuid()
        .optional()
        .describe('Filter results by generation event UUID. Provide this or evaluationId (or both).'),
    result: z.enum(['pass', 'fail', 'na']).optional().describe('Filter by result status: "pass", "fail", or "na".'),
    limit: z
        .number()
        .int()
        .positive()
        .max(200)
        .optional()
        .describe('Maximum number of results. Defaults to 50, max 200.'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { evaluationId, generationId, result, limit } = params

    if (!evaluationId && !generationId) {
        throw new Error('Either evaluationId or generationId must be provided.')
    }

    const projectId = await context.stateManager.getProjectId()

    const queryParams: Record<string, string | number | undefined> = {
        evaluation_id: evaluationId,
        generation_id: generationId,
        result,
        limit,
    }

    const response = await context.api.request({
        method: 'GET',
        path: `/api/environments/${projectId}/llm_analytics/evaluation_results/`,
        query: queryParams,
    })

    return response
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-results',
    schema,
    handler,
})

export default tool
