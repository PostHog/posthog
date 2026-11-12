import { keepPreviousData, type UseQueryResult, useQuery, useQueryClient } from '@tanstack/react-query'
import { useFocusEffect } from 'expo-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    type ExperimentApi,
    type ExperimentExposureResponseApi,
    type ExperimentHealthApi,
    type ExperimentRecalculationJobApi,
    type ExperimentResultsRunApi,
    type ExperimentRunningTimeTargetApi,
    experimentKeys,
} from '@/api/experiments'
import { retryUnlessMissing } from '@/api/reports'
import { useAppActive } from '@/features/handoff/useTaskRun'
import { actionErrorMessage, toError } from '@/lib/errors'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'

import { type ResultsRefreshOutcome, trackExperimentResultsRefreshed } from './detailAnalytics'
import { exposureTotalOf, type RefreshPhase } from './detailModel'
import { type ExperimentStatus, isLiveStatus } from './experimentModel'
import { readExperiments, useExperimentsContext } from './hooks'

/** The Summarize flow's cadence: poll a run every 5 s while the screen is focused, for up to 2 min. */
export const RECALC_POLL_MS = 5_000
export const RECALC_WAIT_MS = 2 * 60_000
/** A just-launched experiment re-reads stored results and exposures this often while focused. */
export const WATCH_POLL_MS = 60_000
/** A 429 without a usable Retry-After still waits this long before the card offers a refresh again. */
const FALLBACK_WINDOW_MS = 60_000

const TARGET_STALE_MS = 5 * 60_000
const HEALTH_STALE_MS = 5 * 60_000
const EXPOSURES_STALE_MS = 60_000

const TERMINAL_RUN = new Set(['completed', 'failed'])

function stateOf<T>(query: UseQueryResult<T, unknown>): QueryState<T> {
    if (query.data !== undefined) {
        return successQuery(query.data, { isRefetching: query.isRefetching, refetch: query.refetch })
    }
    return query.isError ? errorQuery(toError(query.error), query.refetch) : loadingQuery()
}

/** Focused and in the foreground. Every poll on this screen stops when either is false. */
export function useScreenActive(): boolean {
    const [focused, setFocused] = useState(false)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )
    return useAppActive() && focused
}

export function useRunningTimeTarget(
    experiment: ExperimentApi,
    enabled: boolean
): QueryState<ExperimentRunningTimeTargetApi> {
    const { scope, ready, source } = useExperimentsContext()
    const query = useQuery({
        queryKey: experimentKeys.target(scope, experiment.id),
        queryFn: ({ signal }) => readExperiments(() => source.fetchRunningTimeTarget(experiment.id, signal)),
        enabled: ready && enabled,
        staleTime: TARGET_STALE_MS,
        retry: retryUnlessMissing,
    })
    return stateOf(query)
}

export function useHealth(experiment: ExperimentApi, enabled: boolean): QueryState<ExperimentHealthApi> {
    const { scope, ready, source } = useExperimentsContext()
    const query = useQuery({
        queryKey: experimentKeys.health(scope, experiment.id),
        queryFn: ({ signal }) => readExperiments(() => source.fetchHealth(experiment.id, signal)),
        enabled: ready && enabled,
        staleTime: HEALTH_STALE_MS,
        retry: retryUnlessMissing,
    })
    return stateOf(query)
}

export interface ExposuresState {
    query: QueryState<ExperimentExposureResponseApi>
    /** When the shown exposures arrived, or null before the first read. */
    updatedAt: number | null
}

/**
 * `POST query/` with `ExperimentExposureQuery`, evaluated at `asOf`: the stored results' `query_to`, so the counts match
 * the metrics, as on the web. `null` reads up to now, which the Watching card needs. `undefined` waits for the stored
 * results, so the query is not sent twice. While watching it re-reads every minute, focused only.
 */
export function useExposures(
    experiment: ExperimentApi,
    options: { enabled: boolean; watching: boolean; active: boolean; asOf: string | null | undefined }
): ExposuresState {
    const { scope, ready, source } = useExperimentsContext()
    const polling = options.watching && options.active
    const asOf = options.asOf
    const query = useQuery({
        queryKey: experimentKeys.exposures(scope, experiment.id, asOf ?? null),
        queryFn: ({ signal }) => readExperiments(() => source.fetchExposures(experiment, signal, asOf ?? null)),
        enabled: ready && options.enabled && asOf !== undefined,
        staleTime: EXPOSURES_STALE_MS,
        retry: retryUnlessMissing,
        refetchInterval: polling ? WATCH_POLL_MS : false,
        // A new results window changes the key; the old counts stay until the new ones arrive.
        placeholderData: keepPreviousData,
    })
    return { query: stateOf(query), updatedAt: query.dataUpdatedAt || null }
}

/** Where the exposures end: now while watching or without stored results, else the results' `query_to`. */
export function exposuresAsOf(
    latest: ExperimentResultsRunApi | null | undefined,
    latestFailed: boolean,
    watching: boolean
): string | null | undefined {
    if (watching || latestFailed || latest === null) {
        return null
    }
    return latest === undefined ? undefined : (latest.query_to ?? null)
}

export interface WatchingState {
    /** Exposure totals of each read on this visit, oldest first. */
    history: number[]
    live: boolean
}

/**
 * The Watching card's data. Exposures poll through `useExposures`; this re-reads the stored results on the same
 * minute and keeps the totals of each read for the bars. Reads only: it never starts a recalculation.
 */
export function useWatching(
    experiment: ExperimentApi,
    exposures: ExposuresState,
    options: { watching: boolean; active: boolean }
): WatchingState {
    const { scope } = useExperimentsContext()
    const queryClient = useQueryClient()
    const [history, setHistory] = useState<{ at: number; total: number }[]>([])
    const total = exposureTotalOf(exposures.query.data)
    const { updatedAt } = exposures
    useEffect(() => {
        if (!options.watching || total === null || updatedAt === null) {
            return
        }
        setHistory((current) =>
            current.some((entry) => entry.at === updatedAt)
                ? current
                : [...current, { at: updatedAt, total }].slice(-12)
        )
    }, [options.watching, total, updatedAt])
    const polling = options.watching && options.active
    useEffect(() => {
        if (!polling) {
            return undefined
        }
        const timer = setInterval(() => {
            void queryClient.invalidateQueries({ queryKey: experimentKeys.latest(scope, experiment.id) })
        }, WATCH_POLL_MS)
        return () => clearInterval(timer)
    }, [polling, queryClient, scope, experiment.id])
    return useMemo(() => ({ history: history.map((entry) => entry.total), live: polling }), [history, polling])
}

export interface Recalculation {
    phase: RefreshPhase
    /** The RefreshControl spinner: on from the pull until the request and the reads return. */
    pulling: boolean
    onPull: () => void
    /** The stored results come from the run this device started. */
    mineRunId: string | null
}

interface TrackedRun {
    id: string
    total: number
    done: number
}

function trackedFrom(
    job: Pick<ExperimentRecalculationJobApi, 'id' | 'total_metrics' | 'completed_metrics'>
): TrackedRun {
    return { id: job.id, total: job.total_metrics, done: job.completed_metrics }
}

/**
 * Pull to refresh on the experiment screen. On a live experiment a pull starts a recalculation, then polls the run
 * every 5 s while focused, for up to 2 min ("Still working" after that). Inside the server's five-minute window the
 * POST answers 429, so the pull only re-reads and the card counts down `Retry-After`. A run someone else started
 * counts as a wait too. Complete experiments, drafts and experiments too old to recalculate only re-read.
 */
export function useRecalculation(
    experiment: ExperimentApi,
    latest: ExperimentResultsRunApi | null | undefined,
    status: ExperimentStatus,
    onNotice: (text: string) => void
): Recalculation {
    const { scope, ready, source } = useExperimentsContext()
    const queryClient = useQueryClient()
    const active = useScreenActive()
    const id = experiment.id
    const [run, setRun] = useState<TrackedRun | null>(null)
    const [waitingSince, setWaitingSince] = useState<number | null>(null)
    const [timedOut, setTimedOut] = useState(false)
    const [retryAt, setRetryAt] = useState<number | null>(null)
    const [pulling, setPulling] = useState(false)
    const [mineRunId, setMineRunId] = useState<string | null>(null)
    const inFlight = useRef(false)
    // A run the card stopped waiting for is not picked up again from `active_run`, or "Still working" would never stay.
    const released = useRef(new Set<string>())

    const canRecalculate =
        isLiveStatus(status) && Boolean(experiment.start_date) && !latest?.exceeds_recalculation_age_limit
    const polling = run !== null && !timedOut && active
    const runQuery = useQuery({
        queryKey: experimentKeys.run(scope, id, run?.id ?? ''),
        queryFn: ({ signal }) => readExperiments(() => source.fetchResultsRun(id, run?.id ?? '', signal)),
        enabled: ready && run !== null,
        retry: false,
        refetchInterval: polling ? RECALC_POLL_MS : false,
    })

    const reread = useCallback(
        () =>
            queryClient.invalidateQueries(
                { queryKey: experimentKeys.experimentAll(scope, id) },
                { throwOnError: true }
            ),
        [queryClient, scope, id]
    )

    const attach = useCallback((next: TrackedRun) => {
        setRun(next)
        setWaitingSince(Date.now())
        setTimedOut(false)
        setRetryAt(null)
    }, [])

    const detach = useCallback(() => {
        setRun(null)
        setWaitingSince(null)
        setTimedOut(false)
    }, [])

    // Someone else's run, or one from an earlier visit, shows its progress here too.
    const activeRunId = latest?.active_run?.id ?? null
    useEffect(() => {
        if (activeRunId && run === null && canRecalculate && !released.current.has(activeRunId)) {
            attach({ id: activeRunId, total: 0, done: 0 })
        }
    }, [activeRunId, run, canRecalculate, attach])

    const polled = runQuery.data
    useEffect(() => {
        if (!run || !polled || polled.id !== run.id) {
            return
        }
        const done = polled.completed_metrics + polled.failed_metrics
        if (done !== run.done || polled.total_metrics !== run.total) {
            setRun({ id: run.id, total: polled.total_metrics, done })
        }
        if (TERMINAL_RUN.has(polled.status)) {
            released.current.add(run.id)
            detach()
            if (polled.status === 'failed') {
                onNotice("Couldn't recalculate the results. These are the last ones.")
            }
            void reread().catch(() => {
                onNotice("Couldn't load the updated results. Pull to refresh and try again.")
            })
        }
    }, [run, polled, detach, reread, onNotice])

    useEffect(() => {
        if (waitingSince === null || timedOut) {
            return undefined
        }
        const timer = setTimeout(() => setTimedOut(true), Math.max(0, waitingSince + RECALC_WAIT_MS - Date.now()))
        return () => clearTimeout(timer)
    }, [waitingSince, timedOut])

    useEffect(() => {
        if (retryAt === null) {
            return undefined
        }
        const timer = setTimeout(() => setRetryAt(null), Math.max(0, retryAt - Date.now()))
        return () => clearTimeout(timer)
    }, [retryAt])

    const runRef = useRef(run)
    runRef.current = run
    const timedOutRef = useRef(timedOut)
    timedOutRef.current = timedOut
    const refetchRun = runQuery.refetch

    const onPull = useCallback((): void => {
        if (inFlight.current || !ready) {
            return
        }
        inFlight.current = true
        setPulling(true)
        const report = (outcome: ResultsRefreshOutcome): void => trackExperimentResultsRefreshed({ outcome })
        void (async () => {
            try {
                const current = runRef.current
                if (current) {
                    // A pull while waiting checks the run again, and a pull on "Still working" waits another 2 min.
                    if (timedOutRef.current) {
                        setTimedOut(false)
                        setWaitingSince(Date.now())
                    }
                    await Promise.all([refetchRun(), reread()])
                    return
                }
                if (!canRecalculate) {
                    await reread()
                    report('reread')
                    return
                }
                const started = await readExperiments(() => source.startRecalculation(id))
                if (started.run) {
                    report('started')
                    if (!started.run.is_existing) {
                        setMineRunId(started.run.id)
                    }
                    if (started.run.status === 'failed') {
                        released.current.add(started.run.id)
                        onNotice('This experiment started too long ago to recalculate.')
                    } else if (started.run.status !== 'completed') {
                        attach(trackedFrom(started.run))
                    }
                } else {
                    report('window')
                    const wait =
                        started.retryAfterMs && started.retryAfterMs > 0 ? started.retryAfterMs : FALLBACK_WINDOW_MS
                    setRetryAt(Date.now() + wait)
                }
                await reread()
            } catch (error) {
                report('failed')
                onNotice(actionErrorMessage(error))
            } finally {
                inFlight.current = false
                setPulling(false)
            }
        })()
    }, [ready, canRecalculate, source, id, attach, reread, refetchRun, onNotice])

    const phase = useMemo((): RefreshPhase => {
        if (run) {
            return timedOut ? { kind: 'stuck' } : { kind: 'recalculating', done: run.done, total: run.total }
        }
        if (retryAt !== null) {
            return { kind: 'window', retryAt }
        }
        return pulling ? { kind: 'pulling' } : { kind: 'idle' }
    }, [run, timedOut, retryAt, pulling])

    return { phase, pulling, onPull, mineRunId }
}
