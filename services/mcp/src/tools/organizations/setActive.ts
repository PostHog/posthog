import type { z } from 'zod'

import { wrapError } from '@/lib/errors'
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

    // Validate before committing the session: only switch to an org the user can
    // actually access. Previously the orgId was cached before the fetch, so a bad
    // id (or an org the session can't reach) silently "succeeded" and every later
    // call failed with an opaque error instead.
    const orgResult = await context.api.organizations().get({ orgId })
    if (!orgResult.success) {
        throw wrapError(
            `Could not switch to organization ${orgId}: it was not found or you don't have access to it. ` +
                'Use \`organizations-get\` to list your organizations.',
            orgResult.error
        )
    }

    const org: CachedOrg = orgResult.data
    await context.cache.set('orgId', orgId)
    await context.cache.set(`cachedOrg:${orgId}` as const, org)
    await context.cache.set(`cachedOrgFetchedAt:${orgId}` as const, Date.now())

    // Read cached user and project for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const projectId = (await context.cache.get('projectId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined
    const project = (await context.cache.get(`cachedProject:${projectId}` as const)) as CachedProject | undefined

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
