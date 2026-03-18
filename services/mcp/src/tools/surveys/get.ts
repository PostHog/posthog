import type { z } from 'zod'

import { SURVEY_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { SurveyGetSchema } from '@/schema/tool-inputs'
import { formatSurvey, type FormattedSurvey } from '@/tools/surveys/utils/survey-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = SurveyGetSchema
type Params = z.infer<typeof schema>

export const getHandler: ToolBase<typeof schema, FormattedSurvey>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { surveyId } = params
    const projectId = await context.stateManager.getProjectId()

    const surveyResult = await context.api.surveys({ projectId }).get({
        surveyId,
    })

    if (!surveyResult.success) {
        throw new Error(`Failed to get survey: ${surveyResult.error.message}`)
    }

    const formattedSurvey = formatSurvey(surveyResult.data, context, projectId)

    return formattedSurvey
}

const tool = (): ToolBase<typeof schema, FormattedSurvey> => ({
    name: 'survey-get',
    schema,
    handler: getHandler,
    _meta: {
        ui: {
            resourceUri: SURVEY_RESOURCE_URI,
        },
    },
})

export default tool
