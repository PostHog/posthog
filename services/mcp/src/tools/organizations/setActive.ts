import type { z } from 'zod'

import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedProject, CachedUser, Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

/**
 * Ensure the active project belongs to `orgId`. If the currently active project lives in a
 * different organization (or can't be resolved), re-point to the org's first project so
 * project-scoped tools don't silently keep querying the previous org's data. Returns the
 * project now active in this org, or `undefined` if the org has no accessible projects.
 */
async function reconcileActiveProjectForOrg(context: Context, orgId: string): Promise<CachedProject | undefined> {
    const activeProjectId = await context.cache.get('projectId')

    let activeProject: CachedProject | undefined
    if (activeProjectId) {
        activeProject = (await context.cache.get(`cachedProject:${activeProjectId}` as const)) as
            | CachedProject
            | undefined
        if (!activeProject) {
            const fetched = await context.api.projects().get({ projectId: activeProjectId })
            if (fetched.success) {
                activeProject = fetched.data
            }
        }
    }

    if (activeProject?.organization === orgId) {
        return activeProject
    }

    const projectsResult = await context.api.organizations().projects({ orgId }).list()
    if (projectsResult.success && projectsResult.data.length > 0) {
        const first = projectsResult.data[0]!
        const firstIdStr = first.id.toString()
        await context.cache.set('projectId', firstIdStr)
        await context.cache.set(`cachedProject:${firstIdStr}` as const, first)
        await context.cache.set(`cachedProjectFetchedAt:${firstIdStr}` as const, Date.now())
        return first
    }

    // The org has no accessible projects — clear the stale pointer rather than leave a
    // project from the previous org active.
    await context.cache.delete('projectId')
    return undefined
}

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { orgId } = params
    await context.cache.set('orgId', orgId)

    // Fetch fresh org data and cache it
    let org: CachedOrg | undefined
    const orgResult = await context.api.organizations().get({ orgId })
    if (orgResult.success) {
        org = orgResult.data
        await context.cache.set(`cachedOrg:${orgId}` as const, org)
        await context.cache.set(`cachedOrgFetchedAt:${orgId}` as const, Date.now())
    }

    const project = await reconcileActiveProjectForOrg(context, orgId)

    // Read cached user for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined

    const metadata = buildActiveEnvironmentContextPrompt(user, org, project, context.api.publicBaseUrl)
    const text = metadata
        ? `Switched to organization ${orgId}.\n\nCurrent context:\n${metadata}`
        : `Switched to organization ${orgId}`

    return {
        content: [{ type: 'text', text }],
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'switch-organization',
    schema,
    handler: setActiveHandler,
})

export default tool
