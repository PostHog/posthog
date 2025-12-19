import type { z } from 'zod'

import { InsightGenerateHogQLFromQuestionSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightGenerateHogQLFromQuestionSchema

type Params = z.infer<typeof schema>

export const generateHogQLHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { question } = params
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.insights({ projectId }).sqlInsight({ query: question })

    if (!result.success) {
        throw new Error(`Failed to execute SQL insight: ${result.error.message}`)
    }

    if (result.data.length === 0) {
        return {
            content: [
                {
                    type: 'text',
                    text: 'Received an empty SQL insight or no data in the stream.',
                },
            ],
        }
    }
    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'query-generate-hogql-from-question',
    schema,
    handler: generateHogQLHandler,
})

export default tool
