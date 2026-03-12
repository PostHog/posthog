import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { FEATURE_FLAG_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { FeatureFlagGetDefinitionSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

type TResult = (Schemas.FeatureFlag & { __posthogUrl: string }) | { error: string }

const schema = FeatureFlagGetDefinitionSchema

type Params = z.infer<typeof schema>

export const getDefinitionHandler: ToolBase<typeof schema, TResult>['handler'] = async (
    context: Context,
    { flagId, flagKey }: Params
) => {
    if (!flagId && !flagKey) {
        return { error: 'Either flagId or flagKey must be provided.' }
    }

    const projectId = await context.stateManager.getProjectId()

    const baseUrl = context.api.getProjectBaseUrl(projectId)

    if (flagId) {
        const flagResult = await context.api.featureFlags({ projectId }).get({ flagId: String(flagId) })
        if (!flagResult.success) {
            throw new Error(`Failed to get feature flag: ${flagResult.error.message}`)
        }
        return { ...flagResult.data, _posthogUrl: `${baseUrl}/feature_flags/${flagResult.data.id}` }
    }

    if (flagKey) {
        const flagResult = await context.api.featureFlags({ projectId }).findByKey({ key: flagKey })

        if (!flagResult.success) {
            throw new Error(`Failed to find feature flag: ${flagResult.error.message}`)
        }
        if (flagResult.data) {
            return { ...flagResult.data, _posthogUrl: `${baseUrl}/feature_flags/${flagResult.data.id}` }
        }
        return { error: `Flag with key "${flagKey}" not found.` }
    }

    return { error: 'Could not determine or find the feature flag.' }
}

const tool = (): ToolBase<typeof schema, TResult> => ({
    name: 'feature-flag-get-definition',
    schema,
    handler: getDefinitionHandler,
    _meta: {
        ui: {
            resourceUri: FEATURE_FLAG_RESOURCE_URI,
        },
    },
})

export default tool
