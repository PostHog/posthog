import { FeatureFlagGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
<<<<<<< LEFT
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
||||||| BASE
import type { z } from 'zod'
=======
>>>>>>> RIGHT

const schema = FeatureFlagGetAllSchema

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const projectId = await context.stateManager.getProjectId()

    const flagsResult = await context.api.featureFlags({ projectId }).list()

    if (!flagsResult.success) {
        throw new Error(`Failed to get feature flags: ${flagsResult.error.message}`)
    }

    return { content: [{ type: 'text', text: formatResponse(flagsResult.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'feature-flag-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
