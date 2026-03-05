import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    search: z.string().optional().describe('Search evaluations by name or description.'),
    enabled: z.boolean().optional().describe('Filter by enabled status.'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.request({
        method: 'GET',
        path: `/api/environments/${projectId}/evaluations/`,
        query: {
            search: params.search,
            enabled: params.enabled !== undefined ? String(params.enabled) : undefined,
        },
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluations-get',
    schema,
    handler,
})

export default tool
