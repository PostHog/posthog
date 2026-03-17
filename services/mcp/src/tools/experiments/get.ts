import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import type { Experiment } from '@/schema/experiments'
import { ExperimentGetSchema } from '@/schema/tool-inputs'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ExperimentGetSchema

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<Experiment>

export const getHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    { experimentId }: Params
) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.experiments({ projectId }).get({
        experimentId: experimentId,
    })

    if (!result.success) {
        throw new Error(`Failed to get experiment: ${result.error.message}`)
    }

    return withPostHogUrl(result.data, `${context.api.getProjectBaseUrl(projectId)}/experiments/${result.data.id}`)
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('experiment', {
        name: 'experiment-get',
        schema,
        handler: getHandler,
    })
