

import { SurveyUpdateSchema } from '@/schema/tool-inputs'
import { formatSurvey } from '@/tools/surveys/utils/survey-utils'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = SurveyUpdateSchema
type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { surveyId, ...data } = params

    const projectId = await context.stateManager.getProjectId()

    if (data.questions) {
        data.questions = data.questions.map((question: any) => {
            // Handle single choice questions - convert numeric keys to strings
            if (
                'branching' in question &&
                question.branching?.type === 'response_based' &&
                question.type === 'single_choice'
            ) {
                question.branching.responseValues = Object.fromEntries(
                    Object.entries(question.branching.responseValues).map(([key, value]) => {
                        return [String(key), value]
                    })
                )
            }
            return question
        })
    }

    const surveyResult = await context.api.surveys({ projectId }).update({
        surveyId,
        data,
    })

    if (!surveyResult.success) {
        throw new Error(`Failed to update survey: ${surveyResult.error.message}`)
    }

    const formattedSurvey = formatSurvey(surveyResult.data, context, projectId)

    return {
        content: [{ type: 'text', text: formatResponse(formattedSurvey) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'survey-update',
    schema,
    handler: updateHandler,
})

export default tool
