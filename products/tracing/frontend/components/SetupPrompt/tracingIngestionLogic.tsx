import { afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { retryWithBackoff } from 'lib/utils/async'

import type { tracingIngestionLogicType } from './tracingIngestionLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const tracingIngestionLogic = kea<tracingIngestionLogicType>([
    path(['products', 'tracing', 'components', 'SetupPrompt', 'tracingIngestionLogic']),
    loaders({
        teamHasSpans: {
            __default: undefined as boolean | undefined,
            loadTeamHasSpans: async (): Promise<boolean> => {
                return await retryWithBackoff(() => api.tracing.hasSpans(), { maxAttempts: 3 })
            },
        },
    }),

    reducers({
        teamHasSpansCheckFailed: [
            false,
            {
                loadTeamHasSpans: () => false,
                loadTeamHasSpansSuccess: () => false,
                loadTeamHasSpansFailure: () => true,
            },
        ],
        cachedTeamHasSpans: [
            null as boolean | null,
            { persist: true, prefix: `${teamId}__` },
            {
                // Only cache true - spans don't disappear once ingested
                loadTeamHasSpansSuccess: (_, { teamHasSpans }) => teamHasSpans || null,
            },
        ],
    }),

    selectors({
        hasSpans: [
            (s) => [s.teamHasSpans, s.cachedTeamHasSpans],
            (teamHasSpans, cachedTeamHasSpans): boolean | undefined => teamHasSpans ?? cachedTeamHasSpans ?? undefined,
        ],
    }),

    afterMount(({ actions, values }) => {
        if (values.cachedTeamHasSpans !== true) {
            actions.loadTeamHasSpans()
        }
    }),
])
