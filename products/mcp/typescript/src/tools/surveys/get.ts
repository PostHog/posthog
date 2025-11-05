import { SurveyGetSchema } from '@/schema/tool-inputs'
import { formatSurvey } from '@/tools/surveys/utils/survey-utils'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = SurveyGetSchema
type Params = z.infer<typeof schema>

export const getHandler = async (context: Context, params: Params) => {
    const { surveyId } = params
    const projectId = await context.stateManager.getProjectId()

    const surveyResult = await context.api.surveys({ projectId }).get({
        surveyId,
    })

    if (!surveyResult.success) {
        throw new Error(`Failed to get survey: ${surveyResult.error.message}`)
    }

    const formattedSurvey = formatSurvey(surveyResult.data, context, projectId)

    return {
        content: [{ type: 'text', text: JSON.stringify(formattedSurvey) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'survey-get',
    schema,
    handler: getHandler,
})

export default tool
