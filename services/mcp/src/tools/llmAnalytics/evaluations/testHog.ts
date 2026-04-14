import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    source: z.string().min(1).describe('Hog source code to test. Must return a boolean (true = pass, false = fail).'),
    sample_count: z
        .number()
        .int()
        .min(1)
        .max(10)
        .optional()
        .default(5)
        .describe('Number of recent $ai_generation events to test against (1-10, default 5).'),
    allows_na: z
        .boolean()
        .optional()
        .default(false)
        .describe('Whether the evaluation can return N/A for non-applicable generations.'),
    conditions: z
        .array(z.record(z.string(), z.unknown()))
        .optional()
        .default([])
        .describe('Optional trigger conditions to filter which events are sampled.'),
})

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.request({
        method: 'POST',
        path: `/api/environments/${projectId}/evaluations/test_hog/`,
        body: { ...params },
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-test-hog',
    schema,
    handler,
})

export default tool
