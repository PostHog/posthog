import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FEATURE_FLAG_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { FeatureFlagUpdateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

type TResult = Schemas.FeatureFlag & { __posthogUrl: string }

const schema = FeatureFlagUpdateSchema

type Params = z.infer<typeof schema>

export const updateHandler: ToolBase<typeof schema, TResult>['handler'] = async (context: Context, params: Params) => {
    const { flagKey, data } = params
    const projectId = await context.stateManager.getProjectId()

    const flagResult = await context.api.featureFlags({ projectId }).update({
        key: flagKey,
        data: data,
    })

    if (!flagResult.success) {
        throw new Error(`Failed to update feature flag: ${flagResult.error.message}`)
    }

    return {
        ...flagResult.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${flagResult.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'update-feature-flag',
    schema,
    handler: updateHandler,
    _meta: {
        ui: {
            resourceUri: FEATURE_FLAG_RESOURCE_URI,
        },
    },
})

export default tool
