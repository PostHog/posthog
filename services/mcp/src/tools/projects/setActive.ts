import type { z } from 'zod'

import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { ProjectSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedProject, CachedUser, Context, ToolBase } from '@/tools/types'

const schema = ProjectSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { projectId } = params
    const projectIdStr = projectId.toString()

    await context.cache.set('projectId', projectIdStr)

    // Fetch fresh project data and cache it
    let project: CachedProject | undefined
    const projectResult = await context.api.projects().get({ projectId: projectIdStr })
    if (projectResult.success) {
        project = projectResult.data
        await context.cache.set(`cachedProject:${projectIdStr}` as const, project)
        await context.cache.set(`cachedProjectFetchedAt:${projectIdStr}` as const, Date.now())
    }

    // Reconcile the active org to the project's parent org. Without this the cached `orgId`
    // keeps pointing at the previously active org, so after switching to a project in a
    // different organization the active-environment banner and every org-scoped tool
    // silently disagree with the active project — the agent reads the wrong org's data with
    // no error to flag it.
    let org: CachedOrg | undefined
    const projectOrgId = project?.organization
    if (projectOrgId) {
        await context.cache.set('orgId', projectOrgId)
        org = (await context.cache.get(`cachedOrg:${projectOrgId}` as const)) as CachedOrg | undefined
        if (!org) {
            const orgResult = await context.api.organizations().get({ orgId: projectOrgId })
            if (orgResult.success) {
                org = orgResult.data
                await context.cache.set(`cachedOrg:${projectOrgId}` as const, org)
                await context.cache.set(`cachedOrgFetchedAt:${projectOrgId}` as const, Date.now())
            }
        }
    } else {
        // Project fetch failed — fall back to whatever org is cached so the banner still renders.
        const cachedOrgId = (await context.cache.get('orgId')) ?? 'unknown'
        org = (await context.cache.get(`cachedOrg:${cachedOrgId}` as const)) as CachedOrg | undefined
    }

    // Read cached user for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined

    const metadata = buildActiveEnvironmentContextPrompt(user, org, project, context.api.publicBaseUrl)
    const text = metadata
        ? `Switched to project ${projectId}.\n\nCurrent context:\n${metadata}`
        : `Switched to project ${projectId}`

    return {
        content: [{ type: 'text', text }],
    }
}

const tool = (): ToolBase<typeof schema, Result> => ({
    name: 'switch-project',
    schema,
    handler: setActiveHandler,
})

export default tool
