import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ToolInputValidationError } from '@/lib/errors'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

/**
 * `feature-flag-get-definition-by-key` fetches a flag by its string key.
 *
 * `feature-flag-get-definition` (generated from `feature_flags_retrieve`) only accepts the
 * flag's numeric ID, but the identifier agents naturally have is the key — the string they see
 * in the UI and in code. This hand-written tool resolves a key to its flag via the list
 * endpoint's `key` filter (a case-insensitive exact match), narrowed to the exact-case match
 * when the filter returns more than one case-variant.
 */
const schema = z.object({
    key: z.string().describe('The feature flag key: the string identifier used in code (e.g. "new-checkout").'),
})

type Params = z.infer<typeof schema>
type Result = WithPostHogUrl<Schemas.FeatureFlag>

const featureFlagGetDefinitionByKey = (): ToolBase<typeof schema, Result> => ({
    name: 'feature-flag-get-definition-by-key',
    schema,
    handler: async (context: Context, params: Params) => {
        const key = params.key.trim()
        if (key === '') {
            throw new ToolInputValidationError('Provide the feature flag key to fetch.')
        }

        const projectId = await context.stateManager.getProjectId()

        // The list endpoint's `key` filter is a case-insensitive exact match, so it can return
        // more than one flag only when two keys differ solely by case — prefer an exact-case
        // match among the results before falling back to whatever case-insensitive match came
        // back. The search result already has the full flag, so it's wrapped directly instead of
        // triggering a redundant fetch-by-id round trip.
        const list = await context.api.request<Schemas.PaginatedFeatureFlagList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/feature_flags/`,
            query: { key, limit: 5 },
        })
        const results = list.results ?? []
        const exact = results.filter((flag) => flag.key === key)
        const matches = exact.length > 0 ? exact : results

        if (matches.length === 0) {
            throw new ToolInputValidationError(
                `No feature flag with key "${key}" found in this project. Use feature-flag-get-all to list ` +
                    'available flags.'
            )
        }
        if (matches.length > 1) {
            const ids = matches.map((flag) => flag.id).join(', ')
            throw new ToolInputValidationError(
                `Multiple feature flags matched key "${key}" (IDs: ${ids}). Pass the numeric \`id\` to ` +
                    'feature-flag-get-definition instead.'
            )
        }
        const flag = matches[0]!
        return await withPostHogUrl(context, flag, `/feature_flags/${flag.id}`)
    },
})

export default featureFlagGetDefinitionByKey
