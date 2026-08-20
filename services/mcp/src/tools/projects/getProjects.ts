import type { Schemas } from '@/api/generated'
import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import { omitResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectGetAllSchema

// Keep project credentials out of the discovery response; `id` is enough to
// correlate a project. Mirrors the exclude list `project-get` applies.
const CREDENTIAL_FIELDS = ['api_token', 'secret_api_token', 'secret_api_token_backup', 'live_events_token']

export const getProjectsHandler: ToolBase<typeof schema, Partial<Schemas.ProjectBackwardCompat>[]>['handler'] = async (
    context: Context
) => {
    const orgId = await context.stateManager.getOrgID()

    const projectsResult = await context.api.organizations().projects({ orgId }).list()

    if (!projectsResult.success) {
        throw new Error(`Failed to get projects: ${projectsResult.error.message}`)
    }

    return projectsResult.data.map((project: Schemas.ProjectBackwardCompat) =>
        omitResponseFields(project, CREDENTIAL_FIELDS)
    )
}

const tool = (): ToolBase<typeof schema, Partial<Schemas.ProjectBackwardCompat>[]> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
