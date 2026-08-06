import type { z } from 'zod'

import { wrapError } from '@/lib/errors'
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

    // Resolve the active org the same way every other org-scoped tool does
    // (`getOrgID` falls back to the API-key default and the cached project),
    // rather than reading the raw `orgId` cache key which is often unset on the
    // first call and would make the org comparison below always look like a switch.
    const activeOrgId = await context.stateManager.getOrgID().catch(() => undefined)
    const activeOrgLabel = activeOrgId ?? 'unknown'

    // Validate before committing the session: only switch to a project the user
    // can actually access. Previously the projectId was cached before the fetch,
    // so a bad id (or a project the session can't reach) silently "succeeded" and
    // every later call failed with an opaque error instead.
    const projectResult = await context.api.projects().get({ projectId: projectIdStr })
    if (!projectResult.success) {
        // Preserve the typed API error as `cause`: a not-found / no-access 404-403
        // is a recoverable agent mistake that `handleToolError` should keep out of
        // exception tracking, while a genuine 5xx still gets captured.
        throw wrapError(
            `Could not switch to project ${projectIdStr}: it was not found or you don't have access to it from the active organization (${activeOrgLabel}). ` +
                'If the project belongs to a different organization, call `organizations-get` to list your organizations, then `switch-organization` to the one that owns it, and retry. ' +
                'Use `projects-get` to see the projects available in the active organization.',
            projectResult.error
        )
    }

    const project: CachedProject = projectResult.data
    await context.cache.set('projectId', projectIdStr)
    await context.cache.set(`cachedProject:${projectIdStr}` as const, project)
    await context.cache.set(`cachedProjectFetchedAt:${projectIdStr}` as const, Date.now())

    // Keep the active organization consistent with the project we just selected.
    // Switching to a project in another organization would otherwise leave
    // org-scoped tools pointed at the wrong organization.
    let orgId = activeOrgId
    let org: CachedOrg | undefined
    let switchedOrg = false
    const projectOrgId = project.organization
    if (projectOrgId && projectOrgId !== activeOrgId) {
        await context.cache.set('orgId', projectOrgId)
        orgId = projectOrgId
        // Only a genuine switch if a different org was already active; when no org
        // was resolved yet we're just establishing context, not switching away.
        switchedOrg = activeOrgId !== undefined
        // Fetch the org through the shared resolver so the scoped-token guard
        // (which skips the non-project-nested `/api/organizations/{id}/` call the
        // backend rejects for project-scoped keys) and org caching stay in one
        // place instead of being duplicated here and drifting.
        org = await context.stateManager.getCachedOrFetchOrg()
    }

    // Read cached user (and org, when we didn't just fetch it) for the metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined
    if (!org && orgId) {
        org = (await context.cache.get(`cachedOrg:${orgId}` as const)) as CachedOrg | undefined
    }

    const orgNote = switchedOrg ? ` (also switched the active organization to ${orgId} to match)` : ''
    const metadata = buildActiveEnvironmentContextPrompt(user, org, project, context.api.publicBaseUrl)
    const text = metadata
        ? `Switched to project ${projectId}${orgNote}.\n\nCurrent context:\n${metadata}`
        : `Switched to project ${projectId}${orgNote}`

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
