import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    evaluationId: z.string().describe('The UUID of the evaluation to run.'),
    target_event_id: z.string().describe('The UUID of the $ai_generation event to evaluate.'),
    timestamp: z.string().describe('ISO 8601 timestamp of the target event (needed for efficient lookup).'),
    event: z.string().optional().describe('Event name. Defaults to "$ai_generation".'),
    distinct_id: z.string().optional().describe('Distinct ID of the event (optional, improves lookup performance).'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const { evaluationId, ...rest } = params
    const body = {
        ...rest,
        evaluation_id: evaluationId,
        event: params.event ?? '$ai_generation',
    }

    const result = await context.api.request({
        method: 'POST',
        path: `/api/environments/${projectId}/evaluation_runs/`,
        body,
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-run',
    schema,
    handler,
})

export default tool
