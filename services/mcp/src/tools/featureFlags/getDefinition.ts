import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { PostHogApiError, ToolInputValidationError } from '@/lib/errors'
import { castStringToInt } from '@/tools/cast-helpers'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

/**
 * `feature-flag-get-definition` accepts the flag's numeric ID *or* its string key.
 *
 * The generated version of this tool (feature_flags_retrieve) only accepted the numeric
 * `id`, so agents that had the flag key — the identifier they see in the UI and in code —
 * failed validation ("missing required parameter: id") or fetched `/feature_flags/undefined/`
 * and got a bare 404. This hand-written replacement resolves a key to its flag, keeps the
 * numeric-id path unchanged, and returns errors that name the expected identifier and tell
 * apart a malformed input from a genuinely absent flag. It overrides the generated tool via
 * HANDWRITTEN_OVERRIDES in tools/index.ts.
 */
const schema = z.object({
    id: z
        .union([z.number(), z.string()])
        .optional()
        .describe(
            "The feature flag's numeric ID (e.g. 1234), as returned by feature-flag-get-all. A flag key string " +
                '(e.g. "new-checkout") is also accepted here and resolved automatically. Provide either `id` or `key`.'
        ),
    key: z
        .string()
        .optional()
        .describe(
            'The feature flag key: the string identifier used in code (e.g. "new-checkout"). Use this when you ' +
                'have the key but not the numeric ID. Provide either `id` or `key`.'
        ),
})

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<Schemas.FeatureFlag>

async function fetchById(context: Context, projectId: string, id: number): Promise<Result> {
    try {
        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/feature_flags/${encodeURIComponent(String(id))}/`,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    } catch (error) {
        // Turn the bare 404 into an actionable message, but keep it a 4xx PostHogApiError so it
        // stays classified as a recoverable agent-input error (not captured as an engineer-facing bug).
        if (error instanceof PostHogApiError && error.status === 404) {
            throw new PostHogApiError({
                status: 404,
                statusText: error.statusText,
                body: error.body,
                url: error.url,
                method: error.method,
                message:
                    `No feature flag with ID ${id} exists in this project. If you have the flag key instead, ` +
                    'pass it as `key`. The flag may also belong to a different project, so use feature-flag-get-all ' +
                    '(optionally with `search`) to list flags accessible with your current API key and project, or ' +
                    'switch-project first.',
            })
        }
        throw error
    }
}

async function resolveKeyToId(context: Context, projectId: string, key: string): Promise<number> {
    // The list endpoint's `search` is a case-insensitive substring match over key/name, so it can
    // return more than the flag we want — narrow to an exact key match before fetching.
    const list = await context.api.request<Schemas.PaginatedFeatureFlagList>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/feature_flags/`,
        query: { search: key, limit: 100 },
    })
    const results = list.results ?? []
    const exact = results.filter((flag) => flag.key === key)
    const matches = exact.length > 0 ? exact : results.filter((flag) => flag.key?.toLowerCase() === key.toLowerCase())

    if (matches.length === 0) {
        throw new ToolInputValidationError(
            `No feature flag with key "${key}" found in this project. Use feature-flag-get-all to list available ` +
                'flags, or pass the numeric `id` if you have it.'
        )
    }
    if (matches.length > 1) {
        const ids = matches.map((flag) => flag.id).join(', ')
        throw new ToolInputValidationError(
            `Multiple feature flags matched key "${key}" (IDs: ${ids}). Pass the numeric \`id\` of the flag you want.`
        )
    }
    return matches[0]!.id
}

const featureFlagGetDefinition = (): ToolBase<typeof schema, Result> => ({
    name: 'feature-flag-get-definition',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()

        // An explicit `key` always resolves by key.
        if (params.key !== undefined && params.key.trim() !== '') {
            const id = await resolveKeyToId(context, projectId, params.key.trim())
            return await fetchById(context, projectId, id)
        }

        if (params.id !== undefined && params.id !== null && String(params.id).trim() !== '') {
            const raw = typeof params.id === 'string' ? params.id.trim() : params.id
            const asInt = castStringToInt(raw)
            if (typeof asInt === 'number' && Number.isInteger(asInt)) {
                return await fetchById(context, projectId, asInt)
            }
            // A non-numeric string in `id` is almost always the flag key.
            const id = await resolveKeyToId(context, projectId, String(raw))
            return await fetchById(context, projectId, id)
        }

        throw new ToolInputValidationError(
            'Provide the feature flag to fetch: pass its numeric `id` (from feature-flag-get-all) or its string `key`.'
        )
    },
})

export default featureFlagGetDefinition
