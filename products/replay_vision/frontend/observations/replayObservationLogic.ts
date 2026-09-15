import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visionObservationsRetrieve, visionObservationsViewedCreate } from '../generated/api'
import type { ReplayObservationApi, VisionObservationsRetrieveParams } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { requestObservationRetry } from '../logics/observationRetry'
import { OBSERVATION_LIST_FILTER_KEYS, OBSERVATION_LIST_URL_PARAM_KEYS } from '../replay_scanners/types'
import { scannerBreadcrumb } from '../utils/breadcrumbs'
import { hasScannerPage, scannerLabel } from '../utils/observation'
import { parseNumericParam } from '../utils/urlParams'
import { observationProgressLogic } from './observationProgressLogic'
import { type ObservationsPage, lastObservationsPage, replayObservationSceneLogic } from './replayObservationSceneLogic'

export interface ReplayObservationLogicProps {
    id: string
}

/** Filters the API types as numbers; the URL only ever carries strings, so these need parsing back. */
const NUMERIC_FILTER_KEYS: readonly string[] = ['min_score', 'max_score']

/** List filters carried in the observation URL; passed to retrieve so prev/next stay within the filtered set. */
export function neighborFilterParams(searchParams: Record<string, unknown>): VisionObservationsRetrieveParams {
    const params: Record<string, string | number> = {}
    for (const key of OBSERVATION_LIST_FILTER_KEYS) {
        const value = searchParams[key]
        if (NUMERIC_FILTER_KEYS.includes(key)) {
            const parsed = parseNumericParam(value)
            if (parsed !== null) {
                params[key] = parsed
            }
        } else if (typeof value === 'string' && value) {
            params[key] = value
        }
    }
    return params as VisionObservationsRetrieveParams
}

/**
 * Where an observation belongs, and so where both ways off its page lead: going back, and retrying.
 *
 * A saved scanner owns its observations and lists them. A one-off scan is owned by the recording it
 * ran from, which is also the safe side of [hasScannerPage] because it always resolves.
 */
export function observationParentUrl(
    observation: ReplayObservationApi,
    returnParams: Record<string, string | number> = {}
): string {
    if (!hasScannerPage(observation)) {
        return urls.replaySingle(observation.session_id)
    }
    // combineUrl with no params returns the path unchanged, so the empty case needs no guard.
    return combineUrl(urls.replayVision(observation.scanner_id), returnParams).url
}

/**
 * The list view an observation was opened from, read back off its own URL, so going back returns to
 * the tab, filters, sort, and page the reader left rather than the scanner's overview.
 */
export function scannerReturnParams(searchParams: Record<string, unknown>): Record<string, string> {
    const params: Record<string, string> = {}
    // `tab` and `q` (the Search tab's query) sit alongside the observations table's own params.
    for (const key of ['tab', 'q', ...OBSERVATION_LIST_URL_PARAM_KEYS]) {
        const value = searchParams[key]
        // The router coerces a param by shape: `page=2` to a number, `q=true` to a boolean. Keep every
        // scalar and stringify it; dropping the coerced ones would lose that filter on the way back.
        if (typeof value === 'string' ? value !== '' : typeof value === 'number' || typeof value === 'boolean') {
            params[key] = String(value)
        }
    }
    return params
}

/** The crumb the observation page's back button returns to. */
export function observationParentBreadcrumb(
    observation: ReplayObservationApi,
    returnParams: Record<string, string | number> = {}
): Breadcrumb {
    if (hasScannerPage(observation)) {
        return scannerBreadcrumb(observation.scanner_id, scannerLabel(observation), returnParams)
    }
    return {
        key: `recording-${observation.session_id}`,
        name: 'Recording',
        path: observationParentUrl(observation),
        iconType: 'session_replay',
    }
}

/** Canonical link to an observation's detail page, carrying list filters so prev/next honors them. */
export function observationDetailUrl(id: string, filterParams: Record<string, string | number>): string {
    return combineUrl(urls.replayVisionObservation(id), filterParams).url
}

export interface ObservationNeighbors {
    previous: string | null
    next: string | null
}

/** Null when a neighbor lies outside the page, or the page was loaded under other filters. */
export function neighborsFromPage(
    page: ObservationsPage,
    index: number,
    neighborParams: VisionObservationsRetrieveParams
): ObservationNeighbors | null {
    if (JSON.stringify(page.filterParams) !== JSON.stringify(neighborParams)) {
        return null
    }
    const offset = (page.number - 1) * page.pageSize + index
    const previous = index > 0 ? page.rows[index - 1].id : offset === 0 ? null : undefined
    const next = index < page.rows.length - 1 ? page.rows[index + 1].id : offset === page.total - 1 ? null : undefined
    return previous === undefined || next === undefined ? null : { previous, next }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayObservationLogicValues {
    loadedObservation: ReplayObservationApi | null
    neighborParams: VisionObservationsRetrieveParams
    neighborsPending: boolean
    nextObservationId: string | null
    observation: ReplayObservationApi | null
    observationLoading: boolean
    pageNeighbors: ObservationNeighbors | null
    previousObservationId: string | null
    retrying: boolean
    seededObservation: ReplayObservationApi | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayObservationLogicActions {
    streamCompleted: () => {
        value: true
    } // observationProgressLogic
    loadObservation: () => {
        value: true
    }
    loadObservationFailure: () => {
        value: true
    }
    loadObservationSuccess: (observation: ReplayObservationApi) => {
        observation: ReplayObservationApi
    }
    markViewed: () => {
        value: true
    }
    retryObservation: () => {
        value: true
    }
    retryObservationFailure: () => {
        value: true
    }
    retryObservationSuccess: () => {
        value: true
    }
    seedObservation: (
        observation: ReplayObservationApi,
        neighbors: ObservationNeighbors | null
    ) => {
        neighbors: ObservationNeighbors | null
        observation: ReplayObservationApi
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayObservationLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        neighborParams: (searchParams: Record<string, any>) => VisionObservationsRetrieveParams
        observation: (
            loadedObservation: ReplayObservationApi | null,
            seededObservation: ReplayObservationApi | null
        ) => ReplayObservationApi | null
        neighborsPending: (
            pageNeighbors: ObservationNeighbors | null,
            loadedObservation: ReplayObservationApi | null,
            observationLoading: boolean
        ) => boolean
        previousObservationId: (
            pageNeighbors: ObservationNeighbors | null,
            observation: ReplayObservationApi | null
        ) => string | null
        nextObservationId: (
            pageNeighbors: ObservationNeighbors | null,
            observation: ReplayObservationApi | null
        ) => string | null
    }
}

export type replayObservationLogicType = MakeLogicType<
    replayObservationLogicValues,
    replayObservationLogicActions,
    ReplayObservationLogicProps,
    replayObservationLogicMeta
>

export const replayObservationLogic = kea<replayObservationLogicType>([
    path(['products', 'replay_vision', 'frontend', 'observations', 'replayObservationLogic']),
    props({} as ReplayObservationLogicProps),
    key((props) => props.id),

    // Mount the SSE progress stream alongside the page and listen for its completion to reload the row.
    connect((props: ReplayObservationLogicProps) => ({
        actions: [observationProgressLogic({ observationId: props.id }), ['streamCompleted']],
    })),

    actions({
        loadObservation: true,
        loadObservationSuccess: (observation: ReplayObservationApi) => ({ observation }),
        loadObservationFailure: true,
        seedObservation: (observation: ReplayObservationApi, neighbors: ObservationNeighbors | null) => ({
            observation,
            neighbors,
        }),
        markViewed: true,
        retryObservation: true,
        retryObservationSuccess: true,
        retryObservationFailure: true,
    }),

    reducers({
        // Two rows, not one: a failed read clears the seed but must keep a row the server already sent.
        seededObservation: [
            null as ReplayObservationApi | null,
            {
                seedObservation: (_, { observation }) => observation,
                loadObservationSuccess: () => null,
                loadObservationFailure: () => null,
            },
        ],
        loadedObservation: [
            null as ReplayObservationApi | null,
            {
                loadObservationSuccess: (_, { observation }) => observation,
            },
        ],
        pageNeighbors: [
            null as ObservationNeighbors | null,
            {
                seedObservation: (_, { neighbors }) => neighbors,
            },
        ],
        observationLoading: [
            true,
            {
                loadObservation: () => true,
                loadObservationSuccess: () => false,
                loadObservationFailure: () => false,
            },
        ],
        retrying: [
            false,
            {
                retryObservation: () => true,
                retryObservationSuccess: () => false,
                retryObservationFailure: () => false,
            },
        ],
    }),

    selectors({
        neighborParams: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, any>): VisionObservationsRetrieveParams => neighborFilterParams(searchParams),
        ],
        observation: [
            (s) => [s.loadedObservation, s.seededObservation],
            (
                loadedObservation: ReplayObservationApi | null,
                seededObservation: ReplayObservationApi | null
            ): ReplayObservationApi | null => loadedObservation ?? seededObservation,
        ],
        neighborsPending: [
            (s) => [s.pageNeighbors, s.loadedObservation, s.observationLoading],
            (
                pageNeighbors: ObservationNeighbors | null,
                loadedObservation: ReplayObservationApi | null,
                observationLoading: boolean
            ): boolean => !pageNeighbors && !loadedObservation && observationLoading,
        ],
        previousObservationId: [
            (s) => [s.pageNeighbors, s.observation],
            (pageNeighbors: ObservationNeighbors | null, observation: ReplayObservationApi | null): string | null =>
                pageNeighbors ? pageNeighbors.previous : (observation?.previous_observation_id ?? null),
        ],
        nextObservationId: [
            (s) => [s.pageNeighbors, s.observation],
            (pageNeighbors: ObservationNeighbors | null, observation: ReplayObservationApi | null): string | null =>
                pageNeighbors ? pageNeighbors.next : (observation?.next_observation_id ?? null),
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        // Poll while in flight as the SSE fallback, on failure too; reducers run first, so `observation` is current.
        const reschedulePoll = (): void => {
            const inFlight = values.observation?.status === 'pending' || values.observation?.status === 'running'
            scheduleObservationPoll(cache.disposables, inFlight, actions.loadObservation)
        }
        // Point the breadcrumb at whatever owns this observation, so "back" returns there instead of the vision home.
        const setParentBreadcrumb = (observation: ReplayObservationApi): void => {
            replayObservationSceneLogic().actions.setParentBreadcrumb(
                observationParentBreadcrumb(observation, scannerReturnParams(router.values.searchParams))
            )
        }
        return {
            loadObservation: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.loadObservationFailure() // Clear the loading flag; a bare return spins forever.
                    return
                }
                try {
                    // Filters only scope the server-side prev/next, which the page may already answer.
                    const response = await visionObservationsRetrieve(
                        String(teamId),
                        props.id,
                        values.pageNeighbors ? undefined : values.neighborParams
                    )
                    actions.loadObservationSuccess(response)
                    setParentBreadcrumb(response)
                } catch (error: any) {
                    // Only toast the initial load — background poll retries would otherwise spam one toast per tick.
                    if (!values.loadedObservation) {
                        lemonToast.error(`Failed to load observation${error.detail ? `: ${error.detail}` : ''}`)
                    }
                    actions.loadObservationFailure()
                }
            },

            loadObservationSuccess: ({ observation }) => {
                reschedulePoll()
                // An in-flight row has no result to read yet.
                if (!observation.viewed && observation.status !== 'pending' && observation.status !== 'running') {
                    actions.markViewed()
                }
            },
            loadObservationFailure: reschedulePoll,

            seedObservation: ({ observation }) => setParentBreadcrumb(observation),

            markViewed: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                try {
                    await visionObservationsViewedCreate(String(teamId), props.id)
                } catch {
                    // The next open retries; not worth a toast.
                }
            },

            retryObservation: async () => {
                // The retried row is deleted, so this page's id dangles afterwards. Hand off to whatever
                // owns the observation, which is where the replacement appears.
                const observation = values.observation
                const lands = observation && hasScannerPage(observation) ? 'scanner page' : 'recording'
                const retried = await requestObservationRetry(
                    props.id,
                    `Retrying scan. The new observation will appear on the ${lands} shortly.`
                )
                if (!retried) {
                    actions.retryObservationFailure()
                    return
                }
                actions.retryObservationSuccess()
                if (!observation) {
                    return
                }
                // Land on the unfiltered parent, not the reader's saved list view: the replacement is
                // pending with no verdict yet, so a filtered or paged list would hide the row we just
                // promised appears "shortly".
                router.actions.push(observationParentUrl(observation))
            },

            // When the stream reports the observation has settled, reload once to render the final result.
            streamCompleted: () => {
                actions.loadObservation()
            },
        }
    }),

    afterMount(({ actions, props, values }) => {
        const page = lastObservationsPage.current
        const index = page ? page.rows.findIndex((row) => row.id === props.id) : -1
        if (page && index !== -1) {
            actions.seedObservation(page.rows[index], neighborsFromPage(page, index, values.neighborParams))
        }
        actions.loadObservation()
    }),
])
