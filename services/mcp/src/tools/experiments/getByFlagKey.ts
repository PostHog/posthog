import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { ToolInputValidationError } from '@/lib/errors'
import { normalizeParamAliases } from '@/tools/cast-helpers'
import { resolveFlagsByKey } from '@/tools/featureFlags/resolveFlagsByKey'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

/**
 * `experiment-get-by-flag-key` fetches an experiment by its feature flag key, the identifier
 * agents hold when `experiment-get` wants a numeric ID. The experiments list has no key filter,
 * but the flag row carries `experiment_set`, so resolving the key to its flag is enough.
 *
 * A miss is data, not an error: the dominant caller is an existence check before
 * `experiment-create` (same pattern as `feature-flag-get-definition-by-key`). Several
 * experiments on one flag is also data, because `experiment-duplicate` reuses the source flag,
 * so re-runs stack up; the tool picks the single live one when there is one and otherwise
 * returns the candidates. Only an ambiguous flag key still throws.
 */
const schema = z.preprocess(
    normalizeParamAliases({ feature_flag_key: ['flagKey', 'flag_key', 'featureFlagKey', 'key'] }),
    z.object({
        feature_flag_key: z
            .string()
            .describe('The experiment\'s feature flag key: the string identifier used in code (e.g. "new-checkout").'),
    })
)

type Params = z.infer<typeof schema>

interface ExperimentCandidate {
    id: number
    name: string
    status: string | null
    archived: boolean
    start_date: string | null
    end_date: string | null
    created_at: string | null
}

interface ExperimentLookupMiss {
    found: false
    /** `no_flag` and `no_experiment` mean the key is free to create on; `ambiguous` means it is not. */
    reason: 'no_flag' | 'no_experiment' | 'ambiguous'
    feature_flag_key: string
    message: string
    /** Set for `ambiguous`: the experiments sharing the flag, none of which stands out as the live one. */
    candidates?: ExperimentCandidate[]
}

type Result = (WithPostHogUrl<Schemas.Experiment> & { found: true }) | ExperimentLookupMiss

type LinkedPick = { experimentId: number } | { candidates: ExperimentCandidate[] }

const toCandidate = (experiment: Schemas.ExperimentBasic, archived: boolean): ExperimentCandidate => ({
    id: experiment.id,
    name: experiment.name,
    status: experiment.status ?? null,
    archived,
    start_date: experiment.start_date ?? null,
    end_date: experiment.end_date ?? null,
    created_at: experiment.created_at ?? null,
})

/** Among several experiments on one flag, the single live one wins, then the single archived one. */
const pickLinkedExperiment = async (context: Context, projectId: string, flagId: number): Promise<LinkedPick> => {
    const listLinked = async (archivedOnly: boolean): Promise<Schemas.ExperimentBasic[]> => {
        const page = await context.api.request<Schemas.PaginatedExperimentBasicList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/experiments/`,
            query: { feature_flag_id: flagId, limit: 50, ...(archivedOnly && { archived: true }) },
        })
        return page.results ?? []
    }
    const live = await listLinked(false)
    if (live.length === 1) {
        return { experimentId: live[0]!.id }
    }
    const archived = await listLinked(true)
    if (live.length === 0 && archived.length === 1) {
        return { experimentId: archived[0]!.id }
    }
    return {
        candidates: [
            ...live.map((experiment) => toCandidate(experiment, false)),
            ...archived.map((experiment) => toCandidate(experiment, true)),
        ],
    }
}

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
                reason: 'no_flag',
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
                reason: 'no_experiment',
                feature_flag_key: key,
                message:
                    `Feature flag "${key}" (ID ${flag.id}) exists but no experiment is linked to it. ` +
                    'Create one with `experiment-create` using this key, or call `experiment-list` to browse existing experiments.',
            }
        }

        let experimentId = experimentIds[0]!
        if (experimentIds.length > 1) {
            const pick = await pickLinkedExperiment(context, projectId, flag.id)
            if ('candidates' in pick) {
                return {
                    found: false,
                    reason: 'ambiguous',
                    feature_flag_key: key,
                    candidates: pick.candidates,
                    message:
                        pick.candidates.length > 0
                            ? `${pick.candidates.length} experiments are linked to feature flag "${key}" (ID ${flag.id}) and ` +
                              'none stands out as the live one. Pick from `candidates` and pass its `id` to `experiment-get`.'
                            : `Feature flag "${key}" (ID ${flag.id}) lists experiments ${experimentIds.join(', ')}, but none ` +
                              'came back from the experiments list. Try `experiment-get` with one of those ids.',
                }
            }
            experimentId = pick.experimentId
        }

        const experiment = await context.api.request<Schemas.Experiment>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/experiments/${encodeURIComponent(String(experimentId))}/`,
        })
        const experimentWithUrl = await withPostHogUrl(context, experiment, `/experiments/${experiment.id}`)
        return { ...experimentWithUrl, found: true }
    },
})

export default experimentGetByFlagKey
