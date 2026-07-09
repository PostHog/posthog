import { actions, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { visionScannersObservationsList } from '../generated/api'
import type { ReplayObservationApi } from '../generated/api.schemas'
import { OBSERVE_POLL_GRACE_MS, scheduleObservationPoll } from '../logics/observationPolling'
import { replayScannerLogic } from './replayScannerLogic'
import type { scannerRunTabLogicType } from './scannerRunTabLogicType'

export interface RowObservation {
    id: string
    status: ReplayObservationApi['status']
}

export const IN_PROGRESS_STATUSES = new Set<string>(['pending', 'running'])

// Safety net for the click-to-row bridge: if the trigger fails or the observation never lands, self-heal this
// one session's pending flag so its row can't hold the spinner forever. Matches the poll grace window, so a
// legitimately-slow scan surfaces via loadObservations before the timeout fires.
const PENDING_BRIDGE_TIMEOUT_MS = OBSERVE_POLL_GRACE_MS

export interface ScannerRunTabLogicProps {
    scannerId: string
}

/** Backs the on-demand recordings list: per-session observation lookup, scan bridging, and result polling. */
export const scannerRunTabLogic = kea<scannerRunTabLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerRunTabLogic']),
    props({} as ScannerRunTabLogicProps),
    key((props) => props.scannerId),

    connect((props: ScannerRunTabLogicProps) => ({
        actions: [
            replayScannerLogic({ id: props.scannerId }),
            ['triggerOnDemandObservation', 'triggerOnDemandObservationSuccess'],
        ],
    })),

    actions({
        setVisibleSessionIds: (sessionIds: string[]) => ({ sessionIds }),
        startScan: (sessionId: string) => ({ sessionId }),
        markPending: (sessionId: string) => ({ sessionId }),
        clearPending: (sessionId: string) => ({ sessionId }),
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
        // Bridges click-to-row gap, keyed per session so a stuck scan can't block the other rows. Each entry is
        // kept until that session's observation lands (or its safety-net timeout fires), so the row's spinner holds.
        pendingSessionIds: [
            {} as Record<string, true>,
            {
                markPending: (state, { sessionId }) => (state[sessionId] ? state : { ...state, [sessionId]: true }),
                clearPending: (state, { sessionId }) => {
                    if (!(sessionId in state)) {
                        return state
                    }
                    const { [sessionId]: _drop, ...rest } = state
                    return rest
                },
                // A landed observation supersedes the bridge for that session; drop every pending id now present.
                loadObservationsSuccess: (state, { bySession }) => {
                    const next: Record<string, true> = {}
                    let changed = false
                    for (const sessionId of Object.keys(state)) {
                        if (bySession[sessionId]) {
                            changed = true
                        } else {
                            next[sessionId] = true
                        }
                    }
                    return changed ? next : state
                },
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
            (s) => [s.visibleSessionIds, s.observationBySession, s.pendingSessionIds],
            (
                visibleSessionIds: string[],
                observationBySession: Record<string, RowObservation>,
                pendingSessionIds: Record<string, true>
            ): boolean =>
                Object.keys(pendingSessionIds).length > 0 ||
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
                // Per-session guard: only a re-click on the same row is a no-op — other rows scan concurrently.
                if (values.pendingSessionIds[sessionId]) {
                    return
                }
                actions.markPending(sessionId)
                actions.triggerOnDemandObservation(sessionId, true)
                // Self-heal a stuck bridge: the shared trigger failure/success carries no session id, so lean on
                // loadObservations to clear the common case and this keyed timeout to release the rest.
                cache.disposables.add(() => {
                    const id = setTimeout(() => actions.clearPending(sessionId), PENDING_BRIDGE_TIMEOUT_MS)
                    return () => clearTimeout(id)
                }, `pending-${sessionId}`)
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
