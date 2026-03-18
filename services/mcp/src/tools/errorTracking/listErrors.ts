import type { z } from 'zod'

import { ERROR_ISSUE_LIST_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { ErrorTrackingListSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ErrorTrackingListSchema
type Params = z.infer<typeof schema>
type Result = any & { _posthogUrl: string }

export const listErrorsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { orderBy, dateFrom, dateTo, orderDirection, filterTestAccounts, status } = params
    const projectId = await context.stateManager.getProjectId()

    const errorQuery = {
        kind: 'ErrorTrackingQuery',
        orderBy: orderBy || 'occurrences',
        dateRange: {
            date_from: dateFrom || new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
            date_to: dateTo || new Date().toISOString(),
        },
        volumeResolution: 1,
        orderDirection: orderDirection || 'DESC',
        filterTestAccounts: filterTestAccounts ?? true,
        status: status || 'active',
    }

    const errorsResult = await context.api.query({ projectId }).execute({ queryBody: errorQuery })
    if (!errorsResult.success) {
        throw new Error(`Failed to list errors: ${errorsResult.error.message}`)
    }

    return {
        results: errorsResult.data.results,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/error_tracking`,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'list-errors',
    schema,
    handler: listErrorsHandler,
    _meta: {
        ui: {
            resourceUri: ERROR_ISSUE_LIST_RESOURCE_URI,
        },
    },
})

export default tool
