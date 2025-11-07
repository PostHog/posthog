import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = ProjectGetAllSchema

type Params = z.infer<typeof schema>

export const getProjectsHandler = async (context: Context, _params: Params) => {
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
        content: [{ type: 'text', text: JSON.stringify(projectsResult.data) }],
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
