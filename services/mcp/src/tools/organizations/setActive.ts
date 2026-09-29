import type { z } from 'zod'

import { PinnedContextSwitchError } from '@/lib/errors'
import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedProject, Context, ToolBase } from '@/tools/types'

const schema = OrganizationSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { orgId } = params
    // Without a session, the next request applies the pin again: a pinned project
    // brings back its own org. Refuse rather than report a switch that reverts.
    const pinned = context.stateManager.pinnedContext
    if (pinned && !pinned.sessionScoped && pinned.pin.organizationId !== orgId) {
        throw new PinnedContextSwitchError(pinned.pin)
    }
    await context.stateManager.setActiveContext({ orgId })
    // Record the switch on the MCP session so a pinned connection's resent pin
    // doesn't revert it on the next request.
    await context.setSessionActiveContext?.({ orgId })

    // Fetch fresh org data and cache it
    let org: CachedOrg | undefined
    const orgResult = await context.api.organizations().get({ orgId })
    if (orgResult.success) {
        org = orgResult.data
        await context.cache.set(`cachedOrg:${orgId}` as const, org)
        await context.cache.set(`cachedOrgFetchedAt:${orgId}` as const, Date.now())
    }

    // Read cached project for full metadata block
    const projectId = pinned?.projectId ?? (await context.cache.get('projectId')) ?? 'unknown'
    const project = (await context.cache.get(`cachedProject:${projectId}` as const)) as CachedProject | undefined

    const integrationKinds = project
        ? await context.stateManager.getOrFetchIntegrationKinds(String(project.id)).catch(() => undefined)
        : undefined
    const metadata = buildActiveEnvironmentContextPrompt(org, project, context.api.publicBaseUrl, {
        integrationKinds,
    })
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
