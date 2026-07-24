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

interface IncompleteOrganization {
    id: string
    name: string
    error: string
}

interface ProjectsFindResult {
    projects: FoundProject[]
    // Present only when one or more organizations could not be searched. Lets the
    // caller tell "no such project" apart from "the search was incomplete" (a
    // permission gap or a transient error), rather than reading a partial result
    // as authoritative.
    incomplete_organizations?: IncompleteOrganization[]
}

export const findProjectsHandler: ToolBase<typeof schema, ProjectsFindResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof schema>
) => {
    const orgsResult = await context.api.organizations().list()
    if (!orgsResult.success) {
        throw new Error(`Failed to list organizations: ${orgsResult.error.message}`)
    }

    const needle = params.name?.trim().toLowerCase()

    const perOrg = await Promise.all(
        orgsResult.data.map(
            async (
                org: Schemas.OrganizationBasic
            ): Promise<{ projects: FoundProject[]; incomplete?: IncompleteOrganization }> => {
                const projectsResult = await context.api.organizations().projects({ orgId: org.id }).list()
                // Don't fail the whole search when one org can't be read — return its
                // matches empty and record it so the caller knows the result is partial.
                if (!projectsResult.success) {
                    return {
                        projects: [],
                        incomplete: { id: org.id, name: org.name, error: projectsResult.error.message },
                    }
                }
                const projects = projectsResult.data
                    .filter(
                        (project: Schemas.ProjectBackwardCompat) =>
                            !needle || project.name?.toLowerCase().includes(needle)
                    )
                    .map(
                        (project: Schemas.ProjectBackwardCompat): FoundProject => ({
                            id: project.id,
                            name: project.name,
                            organization: org.id,
                            organization_name: org.name,
                        })
                    )
                return { projects }
            }
        )
    )

    const projects = perOrg.flatMap((result) => result.projects)
    const incompleteOrganizations = perOrg.flatMap((result) => (result.incomplete ? [result.incomplete] : []))

    return incompleteOrganizations.length > 0
        ? { projects, incomplete_organizations: incompleteOrganizations }
        : { projects }
}

const tool = (): ToolBase<typeof schema, ProjectsFindResult> => ({
    name: 'projects-find',
    schema,
    handler: findProjectsHandler,
})

export default tool
