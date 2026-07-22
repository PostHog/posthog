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
 *
 * A key that matches no flag is not an error. The dominant caller is an agent checking whether
 * a flag exists before creating it (a read-before-create existence check), so a miss is the
 * expected answer: it returns a structured `{ found: false }` result naming the key and
 * pointing at the list/create path. The caller's next step, creating the flag, doesn't depend
 * on this being an exception. Reuse this not-found-as-data pattern for other existence checks;
 * keep throwing where the caller expects the target to already exist, so a miss signals a
 * genuine problem rather than an expected outcome.
 */
const schema = z.object({
    key: z.string().describe('The feature flag key: the string identifier used in code (e.g. "new-checkout").'),
})

type Params = z.infer<typeof schema>

/** The result shape returned when no flag matches `key`. See the file doc comment for why this is data, not a thrown error. */
interface FeatureFlagLookupMiss {
    found: false
    key: string
    message: string
}

/** Discriminate on `found` in both branches, so callers don't have to test for its absence on a match. */
type Result = (WithPostHogUrl<Schemas.FeatureFlag> & { found: true }) | FeatureFlagLookupMiss

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
            return {
                found: false,
                key,
                message:
                    `No feature flag with key "${key}" exists in this project. ` +
                    'Create it with `create-feature-flag`, or call `feature-flag-get-all` to list existing flags.',
            }
        }
        if (matches.length > 1) {
            // Unlike a miss, this is still an error: the key is ambiguous and the agent can't
            // proceed on its own — it needs the numeric id from a different tool call.
            const ids = matches.map((flag) => flag.id).join(', ')
            throw new ToolInputValidationError(
                `Multiple feature flags matched key "${key}" (IDs: ${ids}). Pass the numeric \`id\` to ` +
                    'feature-flag-get-definition instead.'
            )
        }
        const flag = matches[0]!
        const flagWithUrl = await withPostHogUrl(context, flag, `/feature_flags/${flag.id}`)
        return { ...flagWithUrl, found: true }
    },
})

export default featureFlagGetDefinitionByKey
