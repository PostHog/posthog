import type { z } from 'zod'

import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedProject, CachedUser, Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

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

    // Read cached user and project for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const projectId = (await context.cache.get('projectId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined
    const project = (await context.cache.get(`cachedProject:${projectId}` as const)) as CachedProject | undefined

    const metadata = buildActiveEnvironmentContextPrompt(user, org, project)
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
