import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionObservationsList, visionScannersObserveCreate } from '../generated/api'
import type { ReplayScannerApi, ReplayObservationApi } from '../generated/api.schemas'
import { OBSERVE_POLL_GRACE_MS, scheduleObservationPoll, shouldPollObservations } from './observationPolling'
import { requestObservationRetry } from './observationRetry'
import type { observationsDockLogicType } from './observationsDockLogicType'
import { refreshVisionQuota } from './visionQuotaLogic'
import { visionScannersListLogic } from './visionScannersListLogic'

export interface ObservationsDockLogicProps {
    sessionId: string
}

export const observationsDockLogic = kea<observationsDockLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'observationsDockLogic']),
    props({} as ObservationsDockLogicProps),
    key((props) => props.sessionId),

    connect(() => ({
        // The scanner list is team-wide — shared so per-recording dock instances don't each refetch it.
        values: [visionScannersListLogic, ['scanners']],
    })),

    actions({
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[]) => ({ observations }),
        loadObservationsFailure: true,
        observe: (scannerId: string) => ({ scannerId }),
        observeSuccess: true,
        observeFailure: true,
        retryObservation: (observationId: string) => ({ observationId }),
        retryObservationSuccess: (observationId: string) => ({ observationId }),
        retryObservationFailure: (observationId: string) => ({ observationId }),
        setDockOpen: (open: boolean) => ({ open }),
        setScannerPickerOpen: (open: boolean) => ({ open }),
        setScannerSearch: (search: string) => ({ search }),
    }),

    reducers({
        observations: [
            [] as ReplayObservationApi[],
            {
                loadObservationsSuccess: (_, { observations }) => observations,
            },
        ],
        observationsLoading: [
            false,
            {
                loadObservations: () => true,
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
        observing: [
            false,
            {
                observe: () => true,
                observeSuccess: () => false,
                observeFailure: () => false,
            },
        ],
        dockOpen: [
            false,
            {
                setDockOpen: (_, { open }) => open,
            },
        ],
        scannerPickerOpen: [
            false,
            {
                setScannerPickerOpen: (_, { open }) => open,
            },
        ],
        scannerSearch: [
            '',
            {
                setScannerSearch: (_, { search }) => search,
                // Reset the query each time the picker is opened or closed.
                setScannerPickerOpen: () => '',
            },
        ],
        retryingObservationIds: [
            [] as string[],
            {
                retryObservation: (state: string[], { observationId }: { observationId: string }) => [
                    ...state,
                    observationId,
                ],
                retryObservationSuccess: (state: string[], { observationId }: { observationId: string }) =>
                    state.filter((id) => id !== observationId),
                retryObservationFailure: (state: string[], { observationId }: { observationId: string }) =>
                    state.filter((id) => id !== observationId),
            },
        ],
        pollUntil: [
            0,
            {
                observeSuccess: () => Date.now() + OBSERVE_POLL_GRACE_MS,
                // The replacement row is inserted by the workflow moments after the retry 202 lands.
                retryObservationSuccess: () => Date.now() + OBSERVE_POLL_GRACE_MS,
            },
        ],
    }),

    selectors({
        hasObservationsInFlight: [
            (s) => [s.observations],
            (observations: ReplayObservationApi[]): boolean =>
                observations.some((o) => o.status === 'pending' || o.status === 'running'),
        ],
        filteredScanners: [
            (s) => [s.scanners, s.scannerSearch],
            (scanners: ReplayScannerApi[], scannerSearch: string): ReplayScannerApi[] => {
                const query = scannerSearch.trim().toLowerCase()
                return query ? scanners.filter((scanner) => scanner.name.toLowerCase().includes(query)) : scanners
            },
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        const reschedulePoll = (): void => {
            scheduleObservationPoll(
                cache.disposables,
                shouldPollObservations(values.hasObservationsInFlight, values.pollUntil),
                actions.loadObservations
            )
        }
        return {
            loadObservations: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.loadObservationsFailure() // Clear the loading flag; a bare return spins forever.
                    return
                }
                try {
                    const response = await visionObservationsList(String(teamId), { session_id: props.sessionId })
                    actions.loadObservationsSuccess(response.results ?? [])
                } catch {
                    actions.loadObservationsFailure()
                }
            },

            // Poll while in flight and through the observe grace window; rescheduled on failure so one hiccup can't kill it.
            loadObservationsSuccess: reschedulePoll,
            loadObservationsFailure: reschedulePoll,

            observe: async ({ scannerId }) => {
                actions.setScannerPickerOpen(false)
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.observeFailure()
                    return
                }
                // Backend keys the workflow id on (scanner, session); re-triggering the same pair silently no-ops.
                if (values.observations.some((o) => o.scanner_id === scannerId)) {
                    lemonToast.info('This scanner has already been run on this recording.')
                    actions.observeFailure()
                    actions.setDockOpen(true)
                    return
                }
                try {
                    await visionScannersObserveCreate(String(teamId), scannerId, { session_id: props.sessionId })
                    lemonToast.success('Observation started')
                    actions.observeSuccess()
                    actions.setDockOpen(true)
                    actions.loadObservations()
                    refreshVisionQuota()
                } catch (error: any) {
                    lemonToast.error(`Failed to start observation${error.detail ? `: ${error.detail}` : ''}`)
                    actions.observeFailure()
                }
            },

            retryObservation: async ({ observationId }) => {
                if (!(await requestObservationRetry(observationId))) {
                    actions.retryObservationFailure(observationId)
                    return
                }
                actions.retryObservationSuccess(observationId)
                actions.loadObservations()
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadObservations()
    }),
])
