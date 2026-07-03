import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { visionScannersObservationsList, visionScannersObservationsStatsRetrieve } from '../generated/api'
import type {
    ObservationLabelStatsApi,
    ReplayObservationApi,
    ReplayObservationLabelApi,
    VisionScannersObservationsListParams,
} from '../generated/api.schemas'
import type { scannerQualityLogicType } from './scannerQualityLogicType'

export type RatedFilterValue = 'all' | 'unrated' | 'rated'

export const QUALITY_PAGE_SIZE = 20
export const LABEL_CHART_DAYS = 30

export interface ScannerQualityLogicProps {
    scannerId: string
}

/** State for the Quality tab: succeeded observations to rate, plus the rated-over-time aggregates. */
export const scannerQualityLogic = kea<scannerQualityLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerQualityLogic']),
    props({} as ScannerQualityLogicProps),
    key((props) => props.scannerId),

    actions({
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[], total: number) => ({ observations, total }),
        loadObservationsFailure: true,
        setPage: (page: number) => ({ page }),
        setRatedFilter: (value: RatedFilterValue) => ({ value }),
        labelChanged: (observationId: string, label: ReplayObservationLabelApi | null) => ({ observationId, label }),
        loadLabelStats: true,
        loadLabelStatsSuccess: (stats: ObservationLabelStatsApi) => ({ stats }),
        loadLabelStatsFailure: true,
    }),

    reducers({
        observations: [
            [] as ReplayObservationApi[],
            {
                loadObservationsSuccess: (_, { observations }) => observations,
                // Keep rows in sync with inline ratings so a row remount doesn't resurrect a stale label.
                labelChanged: (state, { observationId, label }) =>
                    state.map((obs) => (obs.id === observationId ? { ...obs, label } : obs)),
            },
        ],
        total: [
            0,
            {
                loadObservationsSuccess: (_, { total }) => total,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => Math.max(1, page),
                setRatedFilter: () => 1,
            },
        ],
        ratedFilter: [
            'all' as RatedFilterValue,
            {
                setRatedFilter: (_, { value }) => value,
            },
        ],
        observationsLoading: [
            true,
            {
                loadObservations: () => true,
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
        labelStats: [
            null as ObservationLabelStatsApi | null,
            {
                loadLabelStatsSuccess: (_, { stats }) => stats,
            },
        ],
        labelStatsLoading: [
            true,
            {
                loadLabelStats: () => true,
                loadLabelStatsSuccess: () => false,
                loadLabelStatsFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        loadObservations: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                // Only succeeded observations carry an output to judge.
                const params: VisionScannersObservationsListParams = {
                    status: 'succeeded',
                    limit: QUALITY_PAGE_SIZE,
                }
                const offset = (values.page - 1) * QUALITY_PAGE_SIZE
                if (offset > 0) {
                    params.offset = offset
                }
                if (values.ratedFilter !== 'all') {
                    params.labeled = values.ratedFilter === 'rated'
                }
                const response = await visionScannersObservationsList(String(teamId), props.scannerId, params)
                actions.loadObservationsSuccess(response.results ?? [], response.count ?? 0)
            } catch {
                actions.loadObservationsFailure()
            }
        },

        setPage: () => actions.loadObservations(),
        setRatedFilter: () => actions.loadObservations(),

        // Refresh the chart shortly after a rating settles; debounced so a burst of ratings loads once.
        labelChanged: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadLabelStats()
        },

        loadLabelStats: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersObservationsStatsRetrieve(String(teamId), props.scannerId, {
                    recent_days: LABEL_CHART_DAYS,
                })
                actions.loadLabelStatsSuccess(response.labels)
            } catch {
                actions.loadLabelStatsFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservations()
        actions.loadLabelStats()
    }),
])
