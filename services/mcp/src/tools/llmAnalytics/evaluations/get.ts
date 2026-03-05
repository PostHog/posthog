import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    evaluationId: z.string().uuid().describe('The UUID of the evaluation to retrieve.'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.request({
        method: 'GET',
        path: `/api/environments/${projectId}/evaluations/${params.evaluationId}/`,
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-get',
    schema,
    handler,
})

export default tool
