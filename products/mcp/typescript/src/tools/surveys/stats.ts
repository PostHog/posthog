import type { z } from 'zod'

import { SurveyStatsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = SurveyStatsSchema
type Params = z.infer<typeof schema>

export const statsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.surveys({ projectId }).stats({
        survey_id: params.survey_id,
        date_from: params.date_from,
        date_to: params.date_to,
    })

    if (!result.success) {
        throw new Error(`Failed to get survey stats: ${result.error.message}`)
    }

    return result.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'survey-stats',
    schema,
    handler: statsHandler,
})

export default tool
