import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { Experiment } from '@/schema/experiments'
import { ExperimentGetAllSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentGetAllSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<{ results: Experiment[] }>

export const getAllHandler: ToolBase<typeof schema, Result>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const results = await context.api.experiments({ projectId }).list({
        params: {
            limit: params.data?.limit,
            offset: params.data?.offset,
        },
    })

    if (!results.success) {
        throw new Error(`Failed to get experiments: ${results.error.message}`)
    }

    return withPostHogUrl({ results: results.data }, `${context.api.getProjectBaseUrl(projectId)}/experiments`)
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('experiment-list', {
        name: 'experiment-get-all',
        schema,
        handler: getAllHandler,
    })
