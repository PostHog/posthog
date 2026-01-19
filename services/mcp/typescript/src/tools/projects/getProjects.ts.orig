import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
<<<<<<< LEFT
import type { z } from 'zod'
import { formatResponse } from '@/integrations/mcp/utils/formatResponse'
||||||| BASE
import type { z } from 'zod'
=======
>>>>>>> RIGHT

const schema = ProjectGetAllSchema

export const getProjectsHandler: ToolBase<typeof schema>['handler'] = async (context: Context) => {
    const orgId = await context.stateManager.getOrgID()

    if (!orgId) {
        throw new Error(
            'API key does not have access to any organizations. This is likely because the API key is scoped to a project, and not an organization.'
        )
    }

    const projectsResult = await context.api.organizations().projects({ orgId }).list()

    if (!projectsResult.success) {
        throw new Error(`Failed to get projects: ${projectsResult.error.message}`)
    }

    return {
        content: [{ type: 'text', text: formatResponse(projectsResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
