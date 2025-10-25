import { SurveyGetAllSchema } from '@/schema/tool-inputs'
import { formatSurveys } from '@/tools/surveys/utils/survey-utils'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = SurveyGetAllSchema
type Params = z.infer<typeof schema>

export const getAllHandler = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const surveysResult = await context.api.surveys({ projectId }).list(params ? { params } : {})

    if (!surveysResult.success) {
        throw new Error(`Failed to get surveys: ${surveysResult.error.message}`)
    }

    const formattedSurveys = formatSurveys(surveysResult.data, context, projectId)

    const response = {
        results: formattedSurveys,
    }

    return {
        content: [{ type: 'text', text: JSON.stringify(response) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'surveys-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
