import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { findPostHogPermissionError, findRecoverableApiError, PostHogApiError } from '@/lib/errors'
import { castStringToInt } from '@/tools/cast-helpers'
import { omitResponseFields } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

const SECRET_PROJECT_FIELDS = [
    'secret_api_token',
    'secret_api_token_backup',
    'live_events_token',
    'default_modifiers',
] as const

const schema = z.object({
    id: z
        .preprocess(
            castStringToInt,
            z.number().int().describe("Project ID. If omitted, returns the caller's active project.").optional()
        )
        .optional(),
})

type Params = z.infer<typeof schema>

/**
 * Shape returned when the requested project can't be reached. It is a normal
 * (non-error) tool result on purpose: an unknown or inaccessible id is a routine
 * agent situation, and answering with the caller's accessible projects plus a
 * recovery path lets the agent self-correct instead of brute-forcing ids against
 * a hard error.
 */
interface ProjectNotAccessibleResult {
    error: string
    requested_project_id: string | number
    accessible_projects: Array<{ id: number; name: string }>
    guidance: string
}

type GetProjectResult = Schemas.ProjectBackwardCompat | ProjectNotAccessibleResult

// A 403/404 from the project retrieve means the id doesn't exist in this org or
// the API key can't see it — recoverable, so degrade gracefully. Anything else
// (5xx, rate limit, auth) is a genuine failure and must propagate.
function isProjectNotAccessibleError(error: unknown): boolean {
    if (findPostHogPermissionError(error)) {
        return true
    }
    const apiError = findRecoverableApiError(error)
    return apiError instanceof PostHogApiError && (apiError.status === 403 || apiError.status === 404)
}

async function buildNotAccessibleResult(
    context: Context,
    orgId: string,
    requestedId: string | number
): Promise<ProjectNotAccessibleResult> {
    let accessibleProjects: Array<{ id: number; name: string }> = []
    try {
        const projectsResult = await context.api.organizations().projects({ orgId }).list()
        if (projectsResult.success) {
            accessibleProjects = projectsResult.data.map((project: Schemas.ProjectBackwardCompat) => ({
                id: project.id,
                name: project.name ?? '',
            }))
        }
    } catch {
        // Listing is best-effort — still return guidance if it fails.
    }

    return {
        error: `Project ${requestedId} was not found in organization ${orgId}, or your API key can't access it.`,
        requested_project_id: requestedId,
        accessible_projects: accessibleProjects,
        guidance:
            'Pick a project id from `accessible_projects` and call `switch-project { projectId: <id> }`, ' +
            'or call `projects-get { name: "<partial name>" }` to resolve a project by name. ' +
            "If the project you want isn't listed, it may belong to a different organization — call " +
            '`organizations-list`, then `switch-organization`, then retry.',
    }
}

export const getProjectHandler: ToolBase<typeof schema, GetProjectResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const orgId = await context.stateManager.getOrgID()
    const id = params.id ?? (await context.stateManager.getProjectId())
    if (!id) {
        throw new Error('id is required. Provide it explicitly or set an active project first.')
    }

    try {
        const result = await context.api.request<Schemas.ProjectBackwardCompat>({
            method: 'GET',
            path: `/api/organizations/${encodeURIComponent(String(orgId))}/projects/${encodeURIComponent(String(id))}/`,
        })
        return omitResponseFields(result, [...SECRET_PROJECT_FIELDS]) as typeof result
    } catch (error) {
        if (isProjectNotAccessibleError(error)) {
            return buildNotAccessibleResult(context, orgId, id)
        }
        throw error
    }
}

const tool = (): ToolBase<typeof schema, GetProjectResult> => ({
    name: 'project-get',
    schema,
    handler: getProjectHandler,
})

export default tool
