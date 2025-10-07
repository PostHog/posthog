import { FeatureFlagGetDefinitionSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = FeatureFlagGetDefinitionSchema

type Params = z.infer<typeof schema>

export const getDefinitionHandler = async (context: Context, { flagId, flagKey }: Params) => {
    if (!flagId && !flagKey) {
        return {
            content: [
                {
                    type: 'text',
                    text: 'Error: Either flagId or flagKey must be provided.',
                },
            ],
        }
    }

    const projectId = await context.stateManager.getProjectId()

    if (flagId) {
        const flagResult = await context.api
            .featureFlags({ projectId })
            .get({ flagId: String(flagId) })
        if (!flagResult.success) {
            throw new Error(`Failed to get feature flag: ${flagResult.error.message}`)
        }
        return {
            content: [{ type: 'text', text: JSON.stringify(flagResult.data) }],
        }
    }

    if (flagKey) {
        const flagResult = await context.api.featureFlags({ projectId }).findByKey({ key: flagKey })

        if (!flagResult.success) {
            throw new Error(`Failed to find feature flag: ${flagResult.error.message}`)
        }
        if (flagResult.data) {
            return {
                content: [{ type: 'text', text: JSON.stringify(flagResult.data) }],
            }
        }
        return {
            content: [
                {
                    type: 'text',
                    text: `Error: Flag with key "${flagKey}" not found.`,
                },
            ],
        }
    }

    return {
        content: [
            {
                type: 'text',
                text: 'Error: Could not determine or find the feature flag.',
            },
        ],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'feature-flag-get-definition',
    schema,
    handler: getDefinitionHandler,
})

export default tool
