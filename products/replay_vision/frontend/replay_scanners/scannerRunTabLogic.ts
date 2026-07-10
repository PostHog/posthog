import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { visionScannersObservationsList } from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { replayScannerLogic } from './replayScannerLogic'
import type { scannerRunTabLogicType } from './scannerRunTabLogicType'

export interface RowObservation {
    id: string
    status: ReplayObservationApi['status']
}

export const IN_PROGRESS_STATUSES = new Set<string>(['pending', 'running'])

export interface ScannerRunTabLogicProps {
    scannerId: string
}

/** Backs the on-demand recordings list: per-session observation lookup, scan bridging, and result polling. */
export const scannerRunTabLogic = kea<scannerRunTabLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerRunTabLogic']),
    props({} as ScannerRunTabLogicProps),
    key((props) => props.scannerId),

    connect((props: ScannerRunTabLogicProps) => ({
        values: [replayScannerLogic({ id: props.scannerId }), ['triggeringOnDemandObservation']],
        actions: [
            replayScannerLogic({ id: props.scannerId }),
            ['triggerOnDemandObservation', 'triggerOnDemandObservationSuccess', 'triggerOnDemandObservationFailure'],
        ],
    })),

    actions({
        setVisibleSessionIds: (sessionIds: string[]) => ({ sessionIds }),
        startScan: (sessionId: string) => ({ sessionId }),
        setPendingId: (sessionId: string) => ({ sessionId }),
        loadObservations: (background = false) => ({ background }),
        loadObservationsSuccess: (bySession: Record<string, RowObservation>) => ({ bySession }),
        loadObservationsFailure: true,
    }),

    reducers({
        visibleSessionIds: [
            [] as string[],
            {
                setVisibleSessionIds: (_, { sessionIds }) => sessionIds,
            },
        ],
        observationBySession: [
            {} as Record<string, RowObservation>,
            {
                // Merge over the previous map so rows scrolled out of the fetch keep their last-known state.
                loadObservationsSuccess: (state, { bySession }) => ({ ...state, ...bySession }),
            },
        ],
        // Bridges click-to-row gap: kept until the observation lands or the trigger fails, so the spinner holds.
        pendingId: [
            null as string | null,
            {
                setPendingId: (_, { sessionId }) => sessionId,
                triggerOnDemandObservationFailure: () => null,
                loadObservationsSuccess: (state, { bySession }) => (state && bySession[state] ? null : state),
            },
        ],
        // Drives the table's loading bar on foreground refetches only; background polls reload silently.
        refreshingObservations: [
            false,
            {
                loadObservations: (state, { background }) => (background ? state : true),
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
    }),

    selectors({
        shouldPoll: [
            (s) => [s.visibleSessionIds, s.observationBySession, s.pendingId],
            (
                visibleSessionIds: string[],
                observationBySession: Record<string, RowObservation>,
                pendingId: string | null
            ): boolean =>
                pendingId !== null ||
                visibleSessionIds.some((id) => {
                    const observation = observationBySession[id]
                    return !!observation && IN_PROGRESS_STATUSES.has(observation.status)
                }),
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        // Rescheduled on failure too — a transient API hiccup shouldn't permanently kill the polling cycle.
        const reschedulePoll = (): void =>
            scheduleObservationPoll(cache.disposables, values.shouldPoll, () => actions.loadObservations(true))
        return {
            setVisibleSessionIds: ({ sessionIds }) => {
                if (sessionIds.length > 0) {
                    actions.loadObservations()
                }
            },

            startScan: ({ sessionId }) => {
                if (values.triggeringOnDemandObservation || values.pendingId) {
                    return
                }
                actions.setPendingId(sessionId)
                actions.triggerOnDemandObservation(sessionId, true)
            },

            // A successful trigger creates a pending observation server-side — refetch to pick it up.
            triggerOnDemandObservationSuccess: () => actions.loadObservations(),

            loadObservations: async (_, breakpoint) => {
                const teamId = teamLogic.values.currentTeamId
                const sessionIds = values.visibleSessionIds
                if (!teamId || sessionIds.length === 0) {
                    actions.loadObservationsFailure() // Clear the foreground loading flag; a bare return spins forever.
                    return
                }
                try {
                    // No limit coupling to visible rows — retries stack observations and a truncated page hides scans.
                    // Ordering pinned: the newest-wins mapping below depends on it, not on the API default.
                    const response = await visionScannersObservationsList(String(teamId), props.scannerId, {
                        session_id: sessionIds.join(','),
                        order_by: '-created_at',
                    })
                    breakpoint()
                    const bySession: Record<string, RowObservation> = {}
                    for (const observation of response.results ?? []) {
                        // Results are newest-first — the first observation per session is the one the row reflects.
                        if (!(observation.session_id in bySession)) {
                            bySession[observation.session_id] = { id: observation.id, status: observation.status }
                        }
                    }
                    actions.loadObservationsSuccess(bySession)
                } catch (error) {
                    if (error instanceof Error && isBreakpoint(error)) {
                        throw error
                    }
                    // Best-effort enrichment — on failure the rows just stay scannable, but keep polling alive.
                    actions.loadObservationsFailure()
                }
            },

            loadObservationsSuccess: reschedulePoll,
            loadObservationsFailure: reschedulePoll,
        }
    }),
])
