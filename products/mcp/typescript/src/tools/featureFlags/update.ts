import type { z } from 'zod'

import { FeatureFlagUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeatureFlagUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const { flagKey, data } = params
    const projectId = await context.stateManager.getProjectId()

    const flagResult = await context.api.featureFlags({ projectId }).update({
        key: flagKey,
        data: data,
    })

    if (!flagResult.success) {
        throw new Error(`Failed to update feature flag: ${flagResult.error.message}`)
    }

    const featureFlagWithUrl = {
        ...flagResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${flagResult.data.id}`,
    }

    return featureFlagWithUrl
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'update-feature-flag',
    schema,
    handler: updateHandler,
})

export default tool
