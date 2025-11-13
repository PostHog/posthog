

import { ErrorTrackingDetailsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'

const schema = ErrorTrackingDetailsSchema

type Params = z.infer<typeof schema>

export const errorDetailsHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { issueId, dateFrom, dateTo } = params
    const projectId = await context.stateManager.getProjectId()

    const errorQuery = {
        kind: 'ErrorTrackingQuery',
        orderBy: 'occurrences',
        dateRange: {
            date_from: dateFrom || new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
            date_to: dateTo || new Date().toISOString(),
        },
        volumeResolution: 0,
        issueId,
    }

    const errorsResult = await context.api.query({ projectId }).execute({ queryBody: errorQuery })
    if (!errorsResult.success) {
        throw new Error(`Failed to get error details: ${errorsResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: formatResponse(errorsResult.data.results) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'error-details',
    schema,
    handler: errorDetailsHandler,
})

export default tool
