import type { Schemas } from '@/api/generated'
import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectGetAllSchema

export const getProjectsHandler: ToolBase<typeof schema, Schemas.ProjectBackwardCompat[]>['handler'] = async (
    context: Context
) => {
    const orgId = await context.stateManager.getOrgID()

    const projectsResult = await context.api.organizations().projects({ orgId }).list()

    if (!projectsResult.success) {
        throw new Error(`Failed to get projects: ${projectsResult.error.message}`)
    }

    return projectsResult.data
}

const tool = (): ToolBase<typeof schema, Schemas.ProjectBackwardCompat[]> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
