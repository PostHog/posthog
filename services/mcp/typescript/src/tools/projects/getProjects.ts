import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

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

    return projectsResult.data
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
