import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { ErrorTrackingListSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ErrorTrackingListSchema
type Params = z.infer<typeof schema>
type Result = WithPostHogUrl

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

    return withPostHogUrl(
        { results: errorsResult.data.results },
        `${context.api.getProjectBaseUrl(projectId)}/error_tracking`
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('error-issue-list', {
        name: 'list-errors',
        schema,
        handler: listErrorsHandler,
    })
