import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ProjectsFindSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = ProjectsFindSchema

interface FoundProject {
    id: number
    name: string | undefined
    organization: string
    organization_name: string
}

export const findProjectsHandler: ToolBase<typeof schema, FoundProject[]>['handler'] = async (
    context: Context,
    params: z.infer<typeof schema>
) => {
    const orgsResult = await context.api.organizations().list()
    if (!orgsResult.success) {
        throw new Error(`Failed to list organizations: ${orgsResult.error.message}`)
    }

    const needle = params.name?.trim().toLowerCase()

    const perOrg = await Promise.all(
        orgsResult.data.map(async (org: Schemas.OrganizationBasic) => {
            const projectsResult = await context.api.organizations().projects({ orgId: org.id }).list()
            // Skip orgs we can't enumerate rather than failing the whole search — the
            // caller still gets matches from the orgs they can access.
            if (!projectsResult.success) {
                return [] as FoundProject[]
            }
            return projectsResult.data
                .filter(
                    (project: Schemas.ProjectBackwardCompat) => !needle || project.name?.toLowerCase().includes(needle)
                )
                .map(
                    (project: Schemas.ProjectBackwardCompat): FoundProject => ({
                        id: project.id,
                        name: project.name,
                        organization: org.id,
                        organization_name: org.name,
                    })
                )
        })
    )

    return perOrg.flat()
}

const tool = (): ToolBase<typeof schema, FoundProject[]> => ({
    name: 'projects-find',
    schema,
    handler: findProjectsHandler,
})

export default tool
