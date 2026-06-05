import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionScannersList, visionScannersObserveCreate, visionObservationsList } from '../generated/api'
import type { ReplayScannerApi, ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from './observationPolling'
import type { observationsDockLogicType } from './observationsDockLogicType'

// The observe endpoint only starts the workflow; its row is created a moment later. Keep polling
// for this window after an observe so the new card appears even before anything reports in flight.
const OBSERVE_POLL_GRACE_MS = 30000

export interface ObservationsDockLogicProps {
    sessionId: string
}

export const observationsDockLogic = kea<observationsDockLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'observationsDockLogic']),
    props({} as ObservationsDockLogicProps),
    key((props) => props.sessionId),

    actions({
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[]) => ({ observations }),
        loadObservationsFailure: true,
        loadScanners: true,
        loadScannersSuccess: (scanners: ReplayScannerApi[]) => ({ scanners }),
        loadScannersFailure: true,
        observe: (scannerId: string) => ({ scannerId }),
        observeSuccess: true,
        observeFailure: true,
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
        scanners: [
            [] as ReplayScannerApi[],
            {
                loadScannersSuccess: (_, { scanners }) => scanners,
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
        pollUntil: [
            0,
            {
                observeSuccess: () => Date.now() + OBSERVE_POLL_GRACE_MS,
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

    listeners(({ actions, props, values, cache }) => ({
        loadObservations: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionObservationsList(String(teamId), { session_id: props.sessionId })
                actions.loadObservationsSuccess(response.results ?? [])
            } catch {
                actions.loadObservationsFailure()
            }
        },

        loadObservationsSuccess: () => {
            // Poll while work is in flight, and through the grace window after an observe.
            scheduleObservationPoll(
                cache.disposables,
                values.hasObservationsInFlight || Date.now() < values.pollUntil,
                actions.loadObservations
            )
        },

        loadScanners: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersList(String(teamId))
                actions.loadScannersSuccess(response.results ?? [])
            } catch {
                actions.loadScannersFailure()
            }
        },

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
            } catch (error: any) {
                lemonToast.error(`Failed to start observation${error.detail ? `: ${error.detail}` : ''}`)
                actions.observeFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadObservations()
        actions.loadScanners()
    }),
])
