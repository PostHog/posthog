import { FeatureFlagGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = FeatureFlagGetAllSchema

type Params = z.infer<typeof schema>

export const getAllHandler = async (context: Context, _params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const flagsResult = await context.api.featureFlags({ projectId }).list()

    if (!flagsResult.success) {
        throw new Error(`Failed to get feature flags: ${flagsResult.error.message}`)
    }

    return { content: [{ type: 'text', text: JSON.stringify(flagsResult.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'feature-flag-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
