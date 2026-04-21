import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    evaluationId: z.string().describe('The UUID of the evaluation to update.'),
    name: z.string().max(400).optional().describe('Updated name.'),
    description: z.string().optional().describe('Updated description.'),
    enabled: z.boolean().optional().describe('Enable or disable the evaluation.'),
    evaluation_config: z
        .object({
            prompt: z.string().optional(),
            source: z.string().optional(),
        })
        .optional()
        .describe('Updated evaluation configuration.'),
    output_config: z
        .object({
            allows_na: z.boolean().optional(),
        })
        .optional()
        .describe('Updated output configuration.'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()
    const { evaluationId, ...body } = params

    const result = await context.api.request({
        method: 'PATCH',
        path: `/api/environments/${projectId}/evaluations/${evaluationId}/`,
        body: body as Record<string, unknown>,
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-update',
    schema,
    handler,
})

export default tool
