import type { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { PinnedContextSwitchError, wrapError } from '@/lib/errors'
import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { OrganizationSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedProject, Context, ToolBase } from '@/tools/types'

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
    if (pinned && !pinned.sessionScoped) {
        const pinnedOrgId = pinned.pin.organizationId ?? (await context.stateManager.getOrgID().catch(() => undefined))
        if (pinnedOrgId !== orgId) {
            throw new PinnedContextSwitchError(pinned.pin)
        }
    }
    const orgResult = await context.api.organizations().get({ orgId })
    if (!orgResult.success) {
        throw wrapError(
            `Could not switch to organization ${orgId}: it was not found or you do not have access. ` +
                'Use `organizations-get` to list available organizations.',
            orgResult.error
        )
    }

    const org: Schemas.Organization = orgResult.data
    const selectedProjectId = pinned?.projectId
    const keepProject = org.id === orgId && org.teams?.some((team) => String(team.id) === selectedProjectId)
    await context.stateManager.setActiveContext({
        orgId,
        ...(keepProject ? { projectId: selectedProjectId } : {}),
    })
    await context.cache.set(`cachedOrg:${orgId}` as const, org)
    await context.cache.set(`cachedOrgFetchedAt:${orgId}` as const, Date.now())

    const projectId = (pinned ? pinned.projectId : await context.cache.get('projectId')) ?? 'unknown'
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
