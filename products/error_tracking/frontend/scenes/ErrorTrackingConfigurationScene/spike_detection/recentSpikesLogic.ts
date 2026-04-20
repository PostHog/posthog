import { actions, afterMount, defaults, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { CountedPaginatedResponse } from 'lib/api'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'

import type { recentSpikesLogicType } from './recentSpikesLogicType'

const RESULTS_PER_PAGE = 10

export type SpikeEventOrder =
    | 'detected_at'
    | '-detected_at'
    | 'computed_baseline'
    | '-computed_baseline'
    | 'current_bucket_value'
    | '-current_bucket_value'

export type RecentSpikesResponse = CountedPaginatedResponse<ErrorTrackingSpikeEvent>

export const recentSpikesLogic = kea<recentSpikesLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'spike_detection',
        'recentSpikesLogic',
    ]),

    actions({
        loadRecentSpikes: true,
        setPage: (page: number) => ({ page }),
        setOrder: (order: SpikeEventOrder) => ({ order }),
    }),

    defaults({
        page: 1 as number,
        order: '-detected_at' as SpikeEventOrder,
        spikesResponse: null as RecentSpikesResponse | null,
    }),

    reducers({
        page: {
            setPage: (_, { page }) => page,
            setOrder: () => 1,
        },
        order: {
            setOrder: (_, { order }) => order,
        },
    }),

    listeners(({ actions }) => ({
        setPage: () => actions.loadRecentSpikes(),
        setOrder: () => actions.loadRecentSpikes(),
    })),

    loaders(({ values }) => ({
        spikesResponse: {
            loadRecentSpikes: async (_, breakpoint) => {
                await breakpoint(100)
                return await api.errorTracking.getSpikeEvents({
                    limit: RESULTS_PER_PAGE,
                    offset: (values.page - 1) * RESULTS_PER_PAGE,
                    orderBy: values.order,
                })
            },
        },
    })),

    selectors(({ actions }) => ({
        recentSpikes: [
            (s) => [s.spikesResponse],
            (response: RecentSpikesResponse | null): ErrorTrackingSpikeEvent[] => response?.results || [],
        ],
        pagination: [
            (s) => [s.page, s.spikesResponse],
            (page: number, response: RecentSpikesResponse | null) => ({
                controlled: true,
                pageSize: RESULTS_PER_PAGE,
                currentPage: page,
                entryCount: response?.count ?? 0,
                onBackward: () => actions.setPage(page - 1),
                onForward: () => actions.setPage(page + 1),
            }),
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadRecentSpikes()
    }),
])
