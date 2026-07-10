import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { environmentVisionQuotaRetrieve } from '../generated/api'
import type { VisionQuotaApi } from '../generated/api.schemas'
import type { visionQuotaLogicType } from './visionQuotaLogicType'

export const visionQuotaLogic = kea<visionQuotaLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'visionQuotaLogic']),

    actions({
        // Declared here so the action stays zero-arg despite the loader's `breakpoint` parameter.
        loadQuota: true,
        // Optimistic shift of the fleet projection (e.g. ±scanner estimate on toggle); loadQuota reconciles.
        adjustProjectedMonthly: (delta: number) => ({ delta }),
    }),

    loaders(({ values }) => ({
        quota: [
            null as VisionQuotaApi | null,
            {
                loadQuota: async (_, breakpoint) => {
                    // Coalesce bursts of post-mutation refetches (e.g. toggling several scanners).
                    await breakpoint(50)
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.quota
                    }
                    try {
                        return await environmentVisionQuotaRetrieve(String(teamId))
                    } catch {
                        // Keep the last-known snapshot — nulling it would silently drop the exhausted-quota guards.
                        return values.quota
                    }
                },
            },
        ],
    })),

    reducers({
        quota: {
            adjustProjectedMonthly: (state: VisionQuotaApi | null, { delta }: { delta: number }) =>
                state
                    ? {
                          ...state,
                          projected_monthly_credits: Math.max(0, state.projected_monthly_credits + delta),
                      }
                    : state,
        },
    }),

    afterMount(({ actions }) => {
        actions.loadQuota()
    }),
])

/** Refresh after any quota-affecting mutation — observes consume quota immediately (in-flight rows count). */
export function refreshVisionQuota(): void {
    visionQuotaLogic.findMounted()?.actions.loadQuota()
}
