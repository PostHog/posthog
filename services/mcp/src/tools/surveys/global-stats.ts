import type { z } from 'zod'

import { SURVEY_GLOBAL_STATS_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { SurveyGlobalStatsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = SurveyGlobalStatsSchema
type Params = z.infer<typeof schema>

export const globalStatsHandler: ToolBase<typeof schema, unknown>['handler'] = async (
    context: Context,
    params: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.surveys({ projectId }).globalStats({ params })

    if (!result.success) {
        throw new Error(`Failed to get survey global stats: ${result.error.message}`)
    }

    return {
        ...result.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/surveys`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'surveys-global-stats',
    schema,
    handler: globalStatsHandler,
    _meta: {
        ui: {
            resourceUri: SURVEY_GLOBAL_STATS_RESOURCE_URI,
        },
    },
})

export default tool
