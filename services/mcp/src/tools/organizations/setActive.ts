import type { z } from 'zod'

import { PostHogApiError, PostHogPermissionError, wrapError } from '@/lib/errors'
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
    const orgResult = await context.api.organizations().get({ orgId })
    if (!orgResult.success) {
        const error = orgResult.error
        const inaccessible =
            error instanceof PostHogPermissionError ||
            (error instanceof PostHogApiError && (error.status === 403 || error.status === 404))
        throw wrapError(
            inaccessible
                ? `Could not switch to organization ${orgId}: it was not found or you don't have access. Use \`organizations-get\` to list available organizations.`
                : `Could not switch to organization ${orgId}: the organization lookup failed, so the active organization was not changed. Try again.`,
            error
        )
    }

    await context.cache.set('orgId', orgId)
    // Record the switch on the MCP session so a pinned connection's resent pin
    // doesn't revert it on the next request.
    await context.setSessionActiveContext?.({ orgId })

    const org = orgResult.data
    await context.cache.set(`cachedOrg:${orgId}` as const, org)
    await context.cache.set(`cachedOrgFetchedAt:${orgId}` as const, Date.now())

    // Read cached project for full metadata block
    const projectId = (await context.cache.get('projectId')) ?? 'unknown'
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
