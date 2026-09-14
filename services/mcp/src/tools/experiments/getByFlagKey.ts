import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ToolInputValidationError } from '@/lib/errors'
import { normalizeParamAliases } from '@/tools/cast-helpers'
import { resolveFlagsByKey } from '@/tools/featureFlags/resolveFlagsByKey'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

/**
 * `experiment-get-by-flag-key` fetches an experiment by its feature flag key.
 *
 * `experiment-get` only accepts the numeric ID, but the identifier agents naturally have is
 * the flag key — the string in code, in the UI, and in `experiment-create`'s own input. The
 * experiments list endpoint has no key filter, but the flag row carries `experiment_set`
 * (every non-deleted experiment linked to the flag, archived included), so resolving the key
 * to its flag is enough to find the experiment.
 *
 * A key that matches nothing is not an error. The dominant caller is an agent checking whether
 * an experiment already exists before creating one, so a miss is the expected answer and comes
 * back as a structured `{ found: false }` result (same pattern as
 * `feature-flag-get-definition-by-key`). An ambiguous match still throws: the agent cannot pick
 * an id on its own.
 */
// Same alias set the flag lookup accepts, plus bare `key`: agents composing this call from the
// tool name reach for any of these. The canonical name still wins on conflict and the advertised
// JSON schema is unchanged (a preprocess renders as the wrapped object).
const schema = z.preprocess(
    normalizeParamAliases({ feature_flag_key: ['flagKey', 'flag_key', 'featureFlagKey', 'key'] }),
    z.object({
        feature_flag_key: z
            .string()
            .describe('The experiment\'s feature flag key: the string identifier used in code (e.g. "new-checkout").'),
    })
)

type Params = z.infer<typeof schema>

/** The result shape returned when no experiment is linked to `feature_flag_key`. See the file doc comment for why this is data, not a thrown error. */
interface ExperimentLookupMiss {
    found: false
    feature_flag_key: string
    message: string
}

/** Discriminate on `found` in both branches, so callers don't have to test for its absence on a match. */
type Result = (WithPostHogUrl<Schemas.Experiment> & { found: true }) | ExperimentLookupMiss

const experimentGetByFlagKey = (): ToolBase<typeof schema, Result> => ({
    name: 'experiment-get-by-flag-key',
    schema,
    handler: async (context: Context, params: Params) => {
        const key = params.feature_flag_key.trim()
        if (key === '') {
            throw new ToolInputValidationError('Provide the feature flag key of the experiment to fetch.')
        }

        const projectId = await context.stateManager.getProjectId()
        const flagMatches = await resolveFlagsByKey(context, projectId, key)

        if (flagMatches.length === 0) {
            return {
                found: false,
                feature_flag_key: key,
                message:
                    `No feature flag with key "${key}" exists in this project, so no experiment is linked to it. ` +
                    'Create one with `experiment-create`, or call `experiment-list` to browse existing experiments.',
            }
        }
        if (flagMatches.length > 1) {
            const ids = flagMatches.map((flag) => flag.id).join(', ')
            throw new ToolInputValidationError(
                `Multiple feature flags matched key "${key}" (IDs: ${ids}). Call \`experiment-list\` with the ` +
                    "right `feature_flag_id`, then pass the experiment's numeric `id` to `experiment-get`."
            )
        }
        const flag = flagMatches[0]!
        const experimentIds = flag.experiment_set ?? []

        if (experimentIds.length === 0) {
            return {
                found: false,
                feature_flag_key: key,
                message:
                    `Feature flag "${key}" (ID ${flag.id}) exists but no experiment is linked to it. ` +
                    'Create one with `experiment-create` using this key, or call `experiment-list` to browse existing experiments.',
            }
        }
        if (experimentIds.length > 1) {
            // Unlike a miss, this is still an error: the key is ambiguous and the agent can't
            // proceed on its own — it needs the numeric id from a different tool call.
            throw new ToolInputValidationError(
                `Multiple experiments are linked to feature flag "${key}" (IDs: ${experimentIds.join(', ')}). ` +
                    'Pass the numeric `id` to `experiment-get` instead.'
            )
        }

        // The flag row carries only the id; fetch the full experiment so the result matches
        // `experiment-get` (metrics, exposure criteria, stats config).
        const experimentId = experimentIds[0]!
        const experiment = await context.api.request<Schemas.Experiment>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(String(experimentId))}/`,
        })
        const experimentWithUrl = await withPostHogUrl(context, experiment, `/experiments/${experiment.id}`)
        return { ...experimentWithUrl, found: true }
    },
})

export default experimentGetByFlagKey
