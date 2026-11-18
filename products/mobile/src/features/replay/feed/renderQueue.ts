import { create } from 'zustand'

import {
    createReplayVideoExport,
    listReplayVideoExports,
    ReplayVideoError,
    type ReplayVideoExport,
    type ReplayVideoRender,
    resolveReplayVideoSource,
    toReplayVideoError,
} from '@/api/replayVideo'
import { sessionGeneration } from '@/auth/tokens'

import { type ReplayVideoState, renderStartedAt, waitForRender } from '../video/useReplayVideo'
import { pickExportFor, type RenderSpec, renderKey } from './feedAdapters'
import { trackFeedRenderFailed, trackFeedRenderReady, trackFeedRenderRequested } from './feedAnalytics'

export type RenderTrigger = 'reuse' | 'dwell' | 'tap'

export interface RenderJob {
    key: string
    spec: RenderSpec
    state: ReplayVideoState
    /** True when this job asked the server for a new video, which counts against the monthly cap. */
    created: boolean
}

interface RenderQueueState {
    jobs: Readonly<Record<string, RenderJob>>
    /** The server's monthly-cap message. Once set, nothing renders again until the app restarts. */
    limitMessage: string | null
}

/**
 * Renders live here, outside any card, so swiping away never cancels one: the poll keeps going and the video is ready
 * when the person comes back. Only a sign-out or an account switch ends a run.
 */
export const useRenderQueue = create<RenderQueueState>(() => ({ jobs: {}, limitMessage: null }))

const running = new Map<string, AbortController>()

function setJob(key: string, update: Partial<RenderJob> | null): void {
    useRenderQueue.setState((store) => {
        const jobs = { ...store.jobs }
        if (update === null) {
            delete jobs[key]
        } else {
            const current = jobs[key]
            if (!current && !update.spec) {
                return store
            }
            jobs[key] = { ...(current as RenderJob), ...update, key }
        }
        return { jobs }
    })
}

export interface StartRender {
    spec: RenderSpec
    known: readonly ReplayVideoExport[] | null
    allowCreate: boolean
    trigger: RenderTrigger
    viewport: Pick<ReplayVideoRender, 'width' | 'height'>
}

/** Does nothing while the same video is checking, rendering or ready, so a second tap never renders twice. */
export function startRender({ spec, known, allowCreate, trigger, viewport }: StartRender): void {
    const key = renderKey(spec)
    const existing = useRenderQueue.getState().jobs[key]
    if (running.has(key) || (existing && existing.state.status !== 'error' && existing.state.status !== 'idle')) {
        return
    }
    const generation = sessionGeneration()
    const controller = new AbortController()
    running.set(key, controller)
    const requestedAt = Date.now()
    let created = false
    const report = (state: ReplayVideoState): boolean => {
        if (sessionGeneration() !== generation) {
            controller.abort()
            setJob(key, null)
            return false
        }
        setJob(key, { spec, state, created })
        return true
    }
    void (async () => {
        try {
            let exports = known
            if (allowCreate || exports === null) {
                if (allowCreate) {
                    report({ status: 'checking' })
                }
                exports = await listReplayVideoExports(spec.sessionId, controller.signal)
            }
            let asset = pickExportFor(exports, spec)
            const reused = asset !== null
            if (!asset) {
                if (!allowCreate) {
                    setJob(key, null)
                    return
                }
                const limit = useRenderQueue.getState().limitMessage
                if (limit !== null) {
                    throw new ReplayVideoError('limit_reached', limit || undefined)
                }
                created = true
                report({ status: 'checking' })
                trackFeedRenderRequested(spec, trigger)
                asset = await createReplayVideoExport(spec.sessionId, spec.durationSeconds, controller.signal, {
                    ...viewport,
                    range:
                        spec.kind === 'clip'
                            ? { startSeconds: spec.startSeconds, endSeconds: spec.endSeconds }
                            : undefined,
                })
            }
            if (asset.exception) {
                throw new ReplayVideoError('render_failed')
            }
            if (!asset.has_content) {
                if (
                    !report({
                        status: 'preparing',
                        exportId: asset.id,
                        startedAt: reused ? renderStartedAt(asset) : Date.now(),
                        reused,
                    })
                ) {
                    return
                }
                asset = await waitForRender(asset.id, controller.signal)
            }
            const source = await resolveReplayVideoSource(asset.id, controller.signal)
            const waitedMs = Date.now() - requestedAt
            if (
                report({
                    status: 'ready',
                    exportId: asset.id,
                    source,
                    context: asset.export_context ?? undefined,
                    reused,
                    waitedMs,
                }) &&
                (created || trigger !== 'reuse')
            ) {
                trackFeedRenderReady(spec, { waitedMs, reused })
            }
        } catch (error) {
            if (controller.signal.aborted) {
                return
            }
            const failure = toReplayVideoError(error)
            if (failure.kind === 'limit_reached') {
                useRenderQueue.setState({ limitMessage: failure.message })
            }
            report({ status: 'error', kind: failure.kind, message: failure.message })
            trackFeedRenderFailed(spec, failure.kind)
        } finally {
            if (running.get(key) === controller) {
                running.delete(key)
            }
        }
    })()
}

export function readyJobFor(jobs: Readonly<Record<string, RenderJob>>, sessionId: string): RenderJob | null {
    const full = jobs[`${sessionId}:full`]
    return full?.state.status === 'ready' ? full : null
}
