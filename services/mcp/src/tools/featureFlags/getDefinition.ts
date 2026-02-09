import type { z } from 'zod'

import { FeatureFlagGetDefinitionSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeatureFlagGetDefinitionSchema

type Params = z.infer<typeof schema>

export const getDefinitionHandler: ToolBase<typeof schema>['handler'] = async (
    context: Context,
    { flagId, flagKey }: Params
) => {
    if (!flagId && !flagKey) {
        return { error: 'Either flagId or flagKey must be provided.' }
    }

    const projectId = await context.stateManager.getProjectId()

    if (flagId) {
        const flagResult = await context.api.featureFlags({ projectId }).get({ flagId: String(flagId) })
        if (!flagResult.success) {
            throw new Error(`Failed to get feature flag: ${flagResult.error.message}`)
        }
        return flagResult.data
    }

    if (flagKey) {
        const flagResult = await context.api.featureFlags({ projectId }).findByKey({ key: flagKey })

        if (!flagResult.success) {
            throw new Error(`Failed to find feature flag: ${flagResult.error.message}`)
        }
        if (flagResult.data) {
            return flagResult.data
        }
        return { error: `Flag with key "${flagKey}" not found.` }
    }

    return { error: 'Could not determine or find the feature flag.' }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'feature-flag-get-definition',
    schema,
    handler: getDefinitionHandler,
})

export default tool
