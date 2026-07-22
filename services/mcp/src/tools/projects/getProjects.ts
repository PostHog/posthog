import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectGetAllSchema

export const getProjectsHandler: ToolBase<typeof schema, Schemas.ProjectBackwardCompat[]>['handler'] = async (
    context: Context,
    params: z.infer<typeof schema>
) => {
    const orgId = await context.stateManager.getOrgID()

    const projectsResult = await context.api.organizations().projects({ orgId }).list()

    if (!projectsResult.success) {
        throw new Error(`Failed to get projects: ${projectsResult.error.message}`)
    }

    const name = params.name?.trim()
    if (!name) {
        return projectsResult.data
    }

    // Client-side substring match: the org's project list is small enough to
    // filter here, and it saves the agent from enumerating ids to find one by name.
    const needle = name.toLowerCase()
    return projectsResult.data.filter((project: Schemas.ProjectBackwardCompat) =>
        project.name?.toLowerCase().includes(needle)
    )
}

const tool = (): ToolBase<typeof schema, Schemas.ProjectBackwardCompat[]> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
