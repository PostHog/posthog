import type { Schemas } from '@/api/generated'
import { ProjectGetAllSchema } from '@/schema/tool-inputs'
import { omitResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectGetAllSchema

// Credentials never belong in a discovery response; `id` is enough to correlate
// a project. A caller that needs the public token asks `project-get` for one
// project, which is the only tool that still returns it.
const CREDENTIAL_FIELDS = [
    'api_token',
    'secret_api_token',
    'secret_api_token_backup',
    'live_events_token',
    'heatmaps_screenshot_secret',
] as const satisfies readonly (keyof Schemas.ProjectBackwardCompat)[]

type PublicProject = Omit<Schemas.ProjectBackwardCompat, (typeof CREDENTIAL_FIELDS)[number]>

export const getProjectsHandler: ToolBase<typeof schema, PublicProject[]>['handler'] = async (context: Context) => {
    const orgId = await context.stateManager.getOrgID()

    const projectsResult = await context.api.organizations().projects({ orgId }).list()

    if (!projectsResult.success) {
        throw new Error(`Failed to get projects: ${projectsResult.error.message}`)
    }

    return projectsResult.data.map(
        (project: Schemas.ProjectBackwardCompat) => omitResponseFields(project, [...CREDENTIAL_FIELDS]) as PublicProject
    )
}

const tool = (): ToolBase<typeof schema, PublicProject[]> => ({
    name: 'projects-get',
    schema,
    handler: getProjectsHandler,
})

export default tool
