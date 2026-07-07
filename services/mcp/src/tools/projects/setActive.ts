import type { z } from 'zod'

import { buildActiveEnvironmentContextPrompt } from '@/lib/instructions'
import { ProjectSetActiveSchema } from '@/schema/tool-inputs'
import type { CachedOrg, CachedUser, Context, ToolBase } from '@/tools/types'

const schema = ProjectSetActiveSchema

type Params = z.infer<typeof schema>

type Result = { content: Array<{ type: string; text: string }> }

// Bound the org fan-out when we build the accessible-projects hint on failure.
// Keys are almost always scoped to a single org, so this only trims pathological
// cases where a user belongs to many orgs.
const MAX_ORGS_FOR_HINT = 10

/**
 * Best-effort list of projects the current key can actually switch to. Used only
 * on the failure path to give the agent a recovery target. Never throws — an
 * empty list just yields a generic hint.
 */
async function listAccessibleProjects(context: Context): Promise<Array<{ id: number; name: string; org: string }>> {
    const [user, apiKey] = await Promise.all([
        context.stateManager.getUser().catch(() => undefined),
        context.stateManager.getApiKey().catch(() => undefined),
    ])

    const scopedOrgs = apiKey?.scoped_organizations ?? []
    const scopedTeams = apiKey?.scoped_teams ?? []
    const orgs = (user?.organizations ?? [])
        .filter((org) => scopedOrgs.length === 0 || scopedOrgs.includes(org.id))
        .slice(0, MAX_ORGS_FOR_HINT)

    const perOrg = await Promise.all(
        orgs.map(async (org) => {
            const result = await context.api.organizations().projects({ orgId: org.id }).list()
            if (!result.success) {
                return []
            }
            return (result.data as Array<{ id: number | string; name?: string | null }>)
                .filter((project) => scopedTeams.length === 0 || scopedTeams.includes(Number(project.id)))
                .map((project) => ({ id: Number(project.id), name: project.name ?? 'unnamed', org: org.name }))
        })
    )

    return perOrg.flat()
}

export const setActiveHandler: ToolBase<typeof schema, Result>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { projectId } = params
    const projectIdStr = projectId.toString()

    // Validate access BEFORE committing the switch. Fetching the project with the
    // current key is the authoritative access check: if it fails, the key can't
    // use this project, and accepting the switch would leave every subsequent
    // tool call returning 403 with no signal that the switch itself was the
    // problem. Fail loudly here instead, and hand the agent the projects it can
    // switch to so it can self-correct.
    const projectResult = await context.api.projects().get({ projectId: projectIdStr })
    if (!projectResult.success) {
        const accessible = await listAccessibleProjects(context)
        const hint = accessible.length
            ? `Projects you can switch to: ${accessible.map((p) => `${p.id} (${p.name}, org: ${p.org})`).join('; ')}.`
            : 'No accessible projects were found for this API key — check that the key is scoped to the intended project.'
        throw new Error(
            `Cannot switch to project ${projectId}: this API key does not have access to it (${projectResult.error.message}). ` +
                `The active project is unchanged. ${hint}`
        )
    }

    const project = projectResult.data
    await context.cache.set('projectId', projectIdStr)
    await context.cache.set(`cachedProject:${projectIdStr}` as const, project)
    await context.cache.set(`cachedProjectFetchedAt:${projectIdStr}` as const, Date.now())

    // Read cached user and org for full metadata block
    const distinctId = (await context.cache.get('distinctId')) ?? 'unknown'
    const orgId = (await context.cache.get('orgId')) ?? 'unknown'
    const user = (await context.cache.get(`cachedUser:${distinctId}` as const)) as CachedUser | undefined
    const org = (await context.cache.get(`cachedOrg:${orgId}` as const)) as CachedOrg | undefined

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
