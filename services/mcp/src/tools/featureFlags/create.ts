import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FeatureFlagCreateSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

type TResult = Schemas.FeatureFlag & { url: string }

const schema = FeatureFlagCreateSchema

type Params = z.infer<typeof schema>

export const createHandler: ToolBase<typeof schema, TResult>['handler'] = async (context: Context, params: Params) => {
    const { name, key, description, filters, active, tags } = params
    const projectId = await context.stateManager.getProjectId()

    const flagResult = await context.api.featureFlags({ projectId }).create({
        data: { name, key, description, filters, active, tags },
    })

    if (!flagResult.success) {
        throw new Error(`Failed to create feature flag: ${flagResult.error.message}`)
    }

    const featureFlagWithUrl = {
        ...flagResult.data,
        url: `${context.api.getProjectBaseUrl(projectId)}/feature_flags/${flagResult.data.id}`,
    }

    return featureFlagWithUrl
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'create-feature-flag',
    schema,
    handler: createHandler,
})

export default tool
