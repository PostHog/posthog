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
import { useAuthStore } from '@/auth/authStore'
import { getSessionTokens, onSessionTokensChanged, sessionGeneration } from '@/auth/tokens'

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
    limitMessage: string | null
    scope: string | null
}

function currentRenderScope(): string | null {
    const { host, projectId } = useAuthStore.getState()
    return host && projectId !== null && getSessionTokens()
        ? JSON.stringify([sessionGeneration(), host, projectId])
        : null
}

// Keep renders alive across card swipes, within the same signed-in project.
export const useRenderQueue = create<RenderQueueState>(() => ({
    jobs: {},
    limitMessage: null,
    scope: currentRenderScope(),
}))

const running = new Map<string, AbortController>()

function syncRenderScope(): void {
    const scope = currentRenderScope()
    if (scope !== useRenderQueue.getState().scope) {
        for (const controller of running.values()) {
            controller.abort()
        }
        running.clear()
        useRenderQueue.setState({ scope, jobs: {}, limitMessage: null })
    }
}

useAuthStore.subscribe(syncRenderScope)
onSessionTokensChanged((change) => {
    if (change === 'session') {
        syncRenderScope()
    }
})

function setJob(key: string, update: Omit<RenderJob, 'key'> | null): void {
    useRenderQueue.setState((store) => {
        const jobs = { ...store.jobs }
        if (update === null) {
            delete jobs[key]
        } else {
            jobs[key] = { ...update, key }
        }
        return { jobs }
    })
}

export interface StartRender {
    spec: RenderSpec
    scope: string | null
    known: readonly ReplayVideoExport[] | null
    reloadSource?: boolean
    allowCreate: boolean
    trigger: RenderTrigger
    viewport: Pick<ReplayVideoRender, 'width' | 'height'>
}

export function startRender({ spec, scope, known, allowCreate, trigger, viewport, reloadSource }: StartRender): void {
    const store = useRenderQueue.getState()
    if (scope === null || scope !== store.scope || scope !== currentRenderScope()) {
        return
    }
    const key = renderKey(spec)
    const existing = store.jobs[key]
    const needsReload = reloadSource && existing?.state.status === 'ready'
    if (
        running.has(key) ||
        (!needsReload && existing && existing.state.status !== 'error' && existing.state.status !== 'idle')
    ) {
        return
    }
    const controller = new AbortController()
    running.set(key, controller)
    const requestedAt = Date.now()
    let created = false
    const isCurrent = (): boolean => running.get(key) === controller && scope === currentRenderScope()
    const report = (state: ReplayVideoState): boolean => {
        if (!isCurrent()) {
            return false
        }
        setJob(key, { spec, state, created })
        return true
    }
    void (async () => {
        try {
            if (allowCreate || needsReload) {
                report({ status: 'checking' })
            }
            const exports =
                allowCreate || needsReload || known === null
                    ? await listReplayVideoExports(spec.sessionId, controller.signal)
                    : known
            if (!isCurrent()) {
                return
            }
            let asset = pickExportFor(exports, spec)
            const reused = asset !== null
            if (!asset) {
                if (!allowCreate) {
                    if (needsReload) {
                        throw new ReplayVideoError('render_failed')
                    }
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
            if (!isCurrent()) {
                return
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
            if (!isCurrent()) {
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
