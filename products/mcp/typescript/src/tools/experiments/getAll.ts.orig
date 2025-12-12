import { ExperimentGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
<<<<<<< LEFT
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
||||||| BASE
import type { z } from 'zod'
=======
>>>>>>> RIGHT

const schema = ExperimentGetAllSchema

export const getAllHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const projectId = await context.stateManager.getProjectId()

    const results = await context.api.experiments({ projectId }).list()

    if (!results.success) {
        throw new Error(`Failed to get experiments: ${results.error.message}`)
    }

    return { content: [{ type: 'text', text: formatResponse(results.data) }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'experiment-get-all',
    schema,
    handler: getAllHandler,
})

export default tool
