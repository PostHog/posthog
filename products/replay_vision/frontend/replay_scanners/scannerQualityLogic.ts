import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    visionScannersObservationsList,
    visionScannersObservationsStatsRetrieve,
    visionScannersPromptSuggestionsApplyCreate,
    visionScannersPromptSuggestionsCurrentRetrieve,
    visionScannersPromptSuggestionsDismissCreate,
    visionScannersPromptSuggestionsEvaluateCreate,
    visionScannersPromptSuggestionsGenerateCreate,
    visionScannersPromptSuggestionsList,
} from '../generated/api'
import type {
    CurrentPromptSuggestionApi,
    ObservationLabelStatsApi,
    ReplayObservationApi,
    ReplayObservationLabelApi,
    ReplayScannerPromptSuggestionApi,
    VisionScannersObservationsListParams,
} from '../generated/api.schemas'
import { ObservationsSorting, replayScannerLogic, resolveOrderByKey } from './replayScannerLogic'
import type { scannerQualityLogicType } from './scannerQualityLogicType'

export type RatedFilterValue = 'all' | 'unrated' | 'rated'

export const QUALITY_PAGE_SIZE = 20
export const LABEL_CHART_DAYS = 30

export interface ScannerQualityLogicProps {
    scannerId: string
}

/** State for the Quality tab: the prompt recommendation, observations to rate, and rated-over-time aggregates. */
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
        setSort: (sorting: ObservationsSorting | null) => ({ sorting }),
        labelChanged: (observationId: string, label: ReplayObservationLabelApi | null) => ({ observationId, label }),
        loadLabelStats: true,
        loadLabelStatsSuccess: (stats: ObservationLabelStatsApi) => ({ stats }),
        loadLabelStatsFailure: true,
        loadCurrentSuggestion: true,
        loadCurrentSuggestionSuccess: (current: CurrentPromptSuggestionApi) => ({ current }),
        loadCurrentSuggestionFailure: true,
        generateSuggestion: true,
        generateSuggestionSuccess: (suggestion: ReplayScannerPromptSuggestionApi) => ({ suggestion }),
        generateSuggestionFailure: true,
        applySuggestion: (suggestionId: string) => ({ suggestionId }),
        applySuggestionSuccess: (suggestion: ReplayScannerPromptSuggestionApi) => ({ suggestion }),
        applySuggestionFailure: true,
        dismissSuggestion: (suggestionId: string) => ({ suggestionId }),
        dismissSuggestionSuccess: (suggestion: ReplayScannerPromptSuggestionApi) => ({ suggestion }),
        dismissSuggestionFailure: true,
        evaluateSuggestion: (suggestionId: string) => ({ suggestionId }),
        evaluateSuggestionSuccess: (suggestion: ReplayScannerPromptSuggestionApi) => ({ suggestion }),
        evaluateSuggestionFailure: true,
        loadSuggestionHistory: true,
        loadSuggestionHistorySuccess: (history: ReplayScannerPromptSuggestionApi[]) => ({ history }),
        loadSuggestionHistoryFailure: true,
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
                setSort: () => 1,
            },
        ],
        sort: [
            { columnKey: 'created_at', order: -1 } as ObservationsSorting | null,
            {
                setSort: (_, { sorting }) => sorting,
            },
        ],
        // Defaults to the not-yet-rated results: the tab's call to action is rating what's still unreviewed.
        ratedFilter: [
            'unrated' as RatedFilterValue,
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
        currentSuggestion: [
            null as ReplayScannerPromptSuggestionApi | null,
            {
                loadCurrentSuggestionSuccess: (_, { current }) => current.suggestion,
                generateSuggestionSuccess: (_, { suggestion }) => suggestion,
                applySuggestionSuccess: (state, { suggestion }) => (state?.id === suggestion.id ? suggestion : state),
                dismissSuggestionSuccess: (state, { suggestion }) => (state?.id === suggestion.id ? suggestion : state),
                evaluateSuggestionSuccess: (state, { suggestion }) =>
                    state?.id === suggestion.id ? suggestion : state,
            },
        ],
        suggestionStale: [
            false,
            {
                loadCurrentSuggestionSuccess: (_, { current }) => current.stale,
                generateSuggestionSuccess: () => false,
            },
        ],
        ratedCount: [
            0,
            {
                loadCurrentSuggestionSuccess: (_, { current }) => current.rated_count,
            },
        ],
        suggestionLoading: [
            true,
            {
                loadCurrentSuggestion: () => true,
                loadCurrentSuggestionSuccess: () => false,
                loadCurrentSuggestionFailure: () => false,
            },
        ],
        generating: [
            false,
            {
                generateSuggestion: () => true,
                generateSuggestionSuccess: () => false,
                generateSuggestionFailure: () => false,
            },
        ],
        applying: [
            false,
            {
                applySuggestion: () => true,
                applySuggestionSuccess: () => false,
                applySuggestionFailure: () => false,
            },
        ],
        dismissing: [
            false,
            {
                dismissSuggestion: () => true,
                dismissSuggestionSuccess: () => false,
                dismissSuggestionFailure: () => false,
            },
        ],
        evaluating: [
            false,
            {
                evaluateSuggestion: () => true,
                evaluateSuggestionSuccess: () => false,
                evaluateSuggestionFailure: () => false,
            },
        ],
        suggestionHistory: [
            [] as ReplayScannerPromptSuggestionApi[],
            {
                loadSuggestionHistorySuccess: (_, { history }) => history,
            },
        ],
        suggestionHistoryLoading: [
            false,
            {
                loadSuggestionHistory: () => true,
                loadSuggestionHistorySuccess: () => false,
                loadSuggestionHistoryFailure: () => false,
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
                if (values.sort) {
                    // The scene keeps the scanner logic mounted, so the type is read lazily for the Result sort key.
                    const scannerType = replayScannerLogic.findMounted({ id: props.scannerId })?.values.scanner
                        ?.scanner_type
                    const orderKey = resolveOrderByKey(values.sort.columnKey, scannerType)
                    if (orderKey) {
                        params.order_by = values.sort.order === -1 ? `-${orderKey}` : orderKey
                    }
                }
                const response = await visionScannersObservationsList(String(teamId), props.scannerId, params)
                actions.loadObservationsSuccess(response.results ?? [], response.count ?? 0)
            } catch {
                // Without this the table shows its filter-specific empty state, which reads as "all rated".
                lemonToast.error("Couldn't load results to rate. Refresh to try again.")
                actions.loadObservationsFailure()
            }
        },

        setPage: () => actions.loadObservations(),
        setRatedFilter: () => actions.loadObservations(),
        setSort: () => actions.loadObservations(),

        // Debounced so a burst of ratings reloads the chart and staleness once.
        labelChanged: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadLabelStats()
            actions.loadCurrentSuggestion()
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

        loadCurrentSuggestion: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersPromptSuggestionsCurrentRetrieve(String(teamId), props.scannerId)
                actions.loadCurrentSuggestionSuccess(response)
            } catch {
                actions.loadCurrentSuggestionFailure()
            }
        },

        // Poll while an evaluation runs. The breakpoint cancels on unmount and re-arms on
        // every refresh, so only one poll chain is alive.
        loadCurrentSuggestionSuccess: async ({ current }, breakpoint) => {
            if (current.suggestion?.evaluation?.status === 'running') {
                await breakpoint(4000)
                actions.loadCurrentSuggestion()
            }
        },

        evaluateSuggestion: async ({ suggestionId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.evaluateSuggestionFailure()
                return
            }
            try {
                const suggestion = await visionScannersPromptSuggestionsEvaluateCreate(
                    String(teamId),
                    props.scannerId,
                    suggestionId
                )
                actions.evaluateSuggestionSuccess(suggestion)
            } catch (error: any) {
                lemonToast.error(`Couldn't start the test${error.detail ? `: ${error.detail}` : ''}`)
                actions.evaluateSuggestionFailure()
            }
        },

        evaluateSuggestionSuccess: async (_, breakpoint) => {
            await breakpoint(4000)
            actions.loadCurrentSuggestion()
        },

        generateSuggestion: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.generateSuggestionFailure()
                return
            }
            try {
                const suggestion = await visionScannersPromptSuggestionsGenerateCreate(String(teamId), props.scannerId)
                actions.generateSuggestionSuccess(suggestion)
            } catch (error: any) {
                lemonToast.error(`Couldn't generate a recommendation${error.detail ? `: ${error.detail}` : ''}`)
                actions.generateSuggestionFailure()
            }
        },

        applySuggestion: async ({ suggestionId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.applySuggestionFailure()
                return
            }
            try {
                const suggestion = await visionScannersPromptSuggestionsApplyCreate(
                    String(teamId),
                    props.scannerId,
                    suggestionId
                )
                actions.applySuggestionSuccess(suggestion)
                lemonToast.success('Prompt applied to the scanner as a new version')
                // The scanner's prompt and version changed, so refresh it wherever the scene shows it.
                replayScannerLogic.findMounted({ id: props.scannerId })?.actions.loadScanner()
            } catch (error: any) {
                lemonToast.error(`Failed to apply the recommendation${error.detail ? `: ${error.detail}` : ''}`)
                actions.applySuggestionFailure()
            }
        },

        dismissSuggestion: async ({ suggestionId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.dismissSuggestionFailure()
                return
            }
            try {
                const suggestion = await visionScannersPromptSuggestionsDismissCreate(
                    String(teamId),
                    props.scannerId,
                    suggestionId
                )
                actions.dismissSuggestionSuccess(suggestion)
            } catch (error: any) {
                lemonToast.error(`Failed to dismiss the recommendation${error.detail ? `: ${error.detail}` : ''}`)
                actions.dismissSuggestionFailure()
            }
        },

        loadSuggestionHistory: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersPromptSuggestionsList(String(teamId), props.scannerId)
                actions.loadSuggestionHistorySuccess(response.results ?? [])
            } catch {
                actions.loadSuggestionHistoryFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservations()
        actions.loadLabelStats()
        actions.loadCurrentSuggestion()
    }),
])
