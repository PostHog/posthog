import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FEATURE_FLAG_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { FeatureFlagCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeatureFlagCreateSchema

type Params = z.infer<typeof schema>
type TResult = Schemas.FeatureFlag & { __posthogUrl: string }

export const createHandler: ToolBase<typeof schema, TResult>['handler'] = async (context: Context, params: Params) => {
    const { name, key, description, filters, active, tags } = params
    const projectId = await context.stateManager.getProjectId()

    const flagResult = await context.api.featureFlags({ projectId }).create({
        data: { name, key, description, filters, active, tags },
    })

    if (!flagResult.success) {
        throw new Error(`Failed to create feature flag: ${flagResult.error.message}`)
    }

    return {
        ...flagResult.data,
        _posthogUrl: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${flagResult.data.id}`,
    }
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'create-feature-flag',
    schema,
    handler: createHandler,
    _meta: {
        ui: {
            resourceUri: FEATURE_FLAG_RESOURCE_URI,
        },
    },
})

export default tool
