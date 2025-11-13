

import { InsightCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = InsightCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { data } = params
    const projectId = await context.stateManager.getProjectId()
    const insightResult = await context.api.insights({ projectId }).create({ data })
    if (!insightResult.success) {
        throw new Error(`Failed to create insight: ${insightResult.error.message}`)
    }

    const insightWithUrl = {
        ...insightResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/insights/${insightResult.data.short_id}`,
    }

    return { content: [{ type: 'text', text: formatResponse(insightWithUrl) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'insight-create-from-query',
    schema,
    handler: createHandler,
})

export default tool
