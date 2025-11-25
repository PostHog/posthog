

import { SurveyGlobalStatsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = SurveyGlobalStatsSchema
type Params = z.infer<typeof schema>

export const globalStatsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.surveys({ projectId }).globalStats({ params })

    if (!result.success) {
        throw new Error(`Failed to get survey global stats: ${result.error.message}`)
    }

    return {
        content: [{ type: 'text', text: formatResponse(result.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'surveys-global-stats',
    schema,
    handler: globalStatsHandler,
})

export default tool
