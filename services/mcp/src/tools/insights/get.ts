import type { z } from 'zod'

import type { Insight } from '@/schema/insights'
import { InsightGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = InsightGetSchema

type Params = z.infer<typeof schema>

type Result = Insight & { url: string }

export const getHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const { insightId } = params
    const projectId = await context.stateManager.getProjectId()
    const insightResult = await context.api.insights({ projectId }).get({ insightId })
    if (!insightResult.success) {
        throw new Error(`Failed to get insight: ${insightResult.error.message}`)
    }

    return {
        ...insightResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'insight-get',
    schema,
    handler: getHandler,
})

export default tool
