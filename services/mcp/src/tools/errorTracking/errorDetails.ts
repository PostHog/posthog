import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { ErrorTrackingDetailsSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ErrorTrackingDetailsSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<{ results: unknown[] }>

export const errorDetailsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
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

    return withPostHogUrl(
        { results: errorsResult.data.results },
        `${context.api.getProjectBaseUrl(projectId)}/error_tracking/${issueId}`
    )
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('error-details', {
        name: 'error-details',
        schema,
        handler: errorDetailsHandler,
    })
