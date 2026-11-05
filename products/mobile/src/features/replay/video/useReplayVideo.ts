import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '@/api/client'
import {
    createReplayVideoExport,
    getReplayVideoExport,
    isTransientReplayVideoError,
    listReplayVideoExports,
    pickReusableExport,
    ReplayVideoError,
    type ReplayVideoErrorKind,
    type ReplayVideoExport,
    type ReplayVideoExportContext,
    type ReplayVideoSource,
    resolveReplayVideoSource,
    toReplayVideoError,
} from '@/api/replayVideo'
import { serverOffsetMs } from '@/api/serverClock'
import { sessionGeneration } from '@/auth/tokens'
import { sleep } from '@/lib/sleep'

export type { ReplayVideoErrorKind } from '@/api/replayVideo'

/**
 * `startedAt` is the device time when the render began, which comes before `start()` for a reused render. `waitedMs`
 * runs from `start()` to ready.
 */
export type ReplayVideoState =
    | { status: 'idle' }
    | { status: 'checking' }
    | { status: 'preparing'; exportId: number; startedAt: number; reused: boolean }
    | {
          status: 'ready'
          exportId: number
          source: ReplayVideoSource
          context: ReplayVideoExportContext | undefined
          reused: boolean
          waitedMs: number
      }
    | { status: 'error'; kind: ReplayVideoErrorKind; message: string }

export interface UseReplayVideo {
    state: ReplayVideoState
    /** Does nothing while a run is in flight, so a second tap never renders the recording twice. */
    start: () => void
    retry: () => void
    reset: () => void
}

export const REPLAY_VIDEO_POLL_MS = 4_000
/** Failed polls in a row before the wait gives up, so a phone that stays offline gets Try again. */
export const REPLAY_VIDEO_MAX_POLL_FAILURES = 5

const IDLE: ReplayVideoState = { status: 'idle' }
const CHECKING: ReplayVideoState = { status: 'checking' }

function nextPollDelay(error: unknown): number {
    const retryAfterSeconds = error instanceof ApiError ? error.retryAfterSeconds : undefined
    return Math.max(REPLAY_VIDEO_POLL_MS, (retryAfterSeconds ?? 0) * 1000)
}

async function waitForRender(exportId: number, signal: AbortSignal): Promise<ReplayVideoExport> {
    let failures = 0
    let delay = REPLAY_VIDEO_POLL_MS
    for (;;) {
        await sleep(delay, signal)
        let asset: ReplayVideoExport
        try {
            asset = await getReplayVideoExport(exportId, signal)
        } catch (error) {
            failures += 1
            if (!isTransientReplayVideoError(error) || failures >= REPLAY_VIDEO_MAX_POLL_FAILURES) {
                throw error
            }
            delay = nextPollDelay(error)
            continue
        }
        if (asset.exception) {
            throw new ReplayVideoError('render_failed')
        }
        if (asset.has_content) {
            return asset
        }
        failures = 0
        delay = REPLAY_VIDEO_POLL_MS
    }
}

/** The render's start on the device clock. `created_at` is a server time. */
function renderStartedAt(asset: ReplayVideoExport): number {
    const created = Date.parse(asset.created_at)
    return Number.isNaN(created) ? Date.now() : created - serverOffsetMs()
}

interface PrepareInput {
    sessionId: string
    durationSeconds: number | null
    signal: AbortSignal
    report: (state: ReplayVideoState) => void
}

async function prepareReplayVideo({
    sessionId,
    durationSeconds,
    signal,
    report,
}: PrepareInput): Promise<ReplayVideoState> {
    const requestedAt = Date.now()
    report(CHECKING)
    const reusable = pickReusableExport(await listReplayVideoExports(sessionId, signal), durationSeconds)
    const reused = reusable !== null
    let asset: ReplayVideoExport
    if (reusable) {
        asset = reusable
    } else {
        if (durationSeconds === null) {
            throw new ReplayVideoError('unknown')
        }
        asset = await createReplayVideoExport(sessionId, durationSeconds, signal)
    }
    if (asset.exception) {
        throw new ReplayVideoError('render_failed')
    }
    if (!asset.has_content) {
        report({
            status: 'preparing',
            exportId: asset.id,
            startedAt: reused ? renderStartedAt(asset) : Date.now(),
            reused,
        })
        asset = await waitForRender(asset.id, signal)
    }
    const source = await resolveReplayVideoSource(asset.id, signal)
    return {
        status: 'ready',
        exportId: asset.id,
        source,
        context: asset.export_context ?? undefined,
        reused,
        waitedMs: Date.now() - requestedAt,
    }
}

interface SessionState {
    sessionId: string
    state: ReplayVideoState
}

export function useReplayVideo({
    sessionId,
    durationSeconds,
}: {
    sessionId: string
    durationSeconds: number | null
}): UseReplayVideo {
    const [entry, setEntry] = useState<SessionState>({ sessionId, state: IDLE })
    const runId = useRef(0)
    const inFlight = useRef<AbortController | null>(null)

    const stop = useCallback((): void => {
        runId.current += 1
        inFlight.current?.abort()
        inFlight.current = null
    }, [])

    const run = useCallback((): void => {
        stop()
        const id = runId.current
        const generation = sessionGeneration()
        const controller = new AbortController()
        inFlight.current = controller
        // A sign-out or a sign-in to another account ends the run: its exports belong to the earlier session.
        const report = (state: ReplayVideoState): void => {
            if (runId.current !== id) {
                return
            }
            if (sessionGeneration() !== generation) {
                stop()
                setEntry({ sessionId, state: IDLE })
                return
            }
            setEntry({ sessionId, state })
        }
        prepareReplayVideo({ sessionId, durationSeconds, signal: controller.signal, report })
            .then(report)
            .catch((error: unknown) => {
                if (!controller.signal.aborted) {
                    const failure = toReplayVideoError(error)
                    report({ status: 'error', kind: failure.kind, message: failure.message })
                }
            })
            .finally(() => {
                if (inFlight.current === controller) {
                    inFlight.current = null
                }
            })
    }, [sessionId, durationSeconds, stop])

    const start = useCallback((): void => {
        if (!inFlight.current) {
            run()
        }
    }, [run])

    const reset = useCallback((): void => {
        stop()
        setEntry({ sessionId, state: IDLE })
    }, [sessionId, stop])

    // Unmounting, or moving to another session, cancels the run, its requests and its timer.
    // biome-ignore lint/correctness/useExhaustiveDependencies: sessionId is the trigger; the cleanup reads nothing from it.
    useEffect(() => stop, [sessionId, stop])

    return { state: entry.sessionId === sessionId ? entry.state : IDLE, start, retry: run, reset }
}
