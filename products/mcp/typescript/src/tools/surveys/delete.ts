import { SurveyDeleteSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = SurveyDeleteSchema
type Params = z.infer<typeof schema>

export const deleteHandler = async (context: Context, params: Params) => {
    const { surveyId } = params
    const projectId = await context.stateManager.getProjectId()

    const deleteResult = await context.api.surveys({ projectId }).delete({
        surveyId,
    })

    if (!deleteResult.success) {
        throw new Error(`Failed to delete survey: ${deleteResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: JSON.stringify(deleteResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'survey-delete',
    schema,
    handler: deleteHandler,
})

export default tool
