import { BudgetExceededError, type BudgetFamily, canSpend } from '@/api/budget'
import { ApiError } from '@/api/client'
import type { InsightRefresh } from '@/api/insights'
import { sleep } from '@/lib/sleep'

import { READ_FLOOR_MS } from './freshness'

export type RefreshMode = InsightRefresh

/** What one read returns. `rate_limited`: the server's query slots were full, and the old value stays. */
export interface ReadResult {
    status: 'ok' | 'failed' | 'rate_limited'
    /** The server computed fresh (`is_cached: false`). */
    computed: boolean
}

/**
 * `skipped`: the item had a request in the last minute. `capped`: its budget bucket was empty, so nothing went out.
 * `aborted`: every screen that wanted it went away before it was sent, or the session ended.
 */
export type JobStatus = 'ok' | 'failed' | 'skipped' | 'capped' | 'aborted'

export interface JobResult {
    status: JobStatus
    computed: boolean
    forced: boolean
    family: BudgetFamily
}

export interface JobRequest {
    /** The freshness key: one cache entry, such as an insight with its dashboard and override. */
    key: string
    family: BudgetFamily
    /** The screen that asks, such as `list` or `dashboard:12`. Leaving the screen drops its queued jobs. */
    group: string
    mode: RefreshMode
    run: (mode: RefreshMode, signal: AbortSignal) => Promise<ReadResult>
    /**
     * A person requested a refresh or retry. The read goes out even inside the automatic minute floor. It still
     * joins a running read, waits out a family pause, and takes a budget token. Callers honor the server's window
     * before requesting a forced recomputation.
     */
    userRetry?: boolean
}

interface Job {
    key: string
    family: BudgetFamily
    mode: RefreshMode
    run: JobRequest['run']
    groups: Set<string>
    state: 'queued' | 'running' | 'waiting'
    retried: boolean
    controller: AbortController | null
    timer: ReturnType<typeof setTimeout> | null
    promise: Promise<JobResult>
    resolve: (result: JobResult) => void
}

const MODE_STRENGTH: Record<RefreshMode, number> = { force_cache: 0, blocking: 1, force_blocking: 2 }

export interface RefreshQueueOptions {
    /** A blocking compute with `from_dashboard` takes one of the org's six dashboard query slots, which the web shares. */
    maxInFlight?: number
    itemFloorMs?: number
    rateLimitRetryMs?: number
    /** The pause after a 429 or 503 without `Retry-After`. */
    defaultPauseMs?: number
    requestDeadlineMs?: number
    now?: () => number
    canSpend?: (family: BudgetFamily) => boolean
}

export class RefreshQueue {
    private readonly maxInFlight: number
    private readonly itemFloorMs: number
    private readonly rateLimitRetryMs: number
    private readonly defaultPauseMs: number
    private readonly requestDeadlineMs: number
    private readonly now: () => number
    private readonly canSpend: (family: BudgetFamily) => boolean

    private readonly jobs = new Map<string, Job>()
    private readonly queue: Job[] = []
    private readonly lastSent = new Map<string, number>()
    private readonly pausedUntil = new Map<BudgetFamily, number>()
    private readonly listeners = new Set<() => void>()
    private running = 0
    private pauseTimer: ReturnType<typeof setTimeout> | null = null
    private pauseTimerUntil: number | null = null

    constructor(options: RefreshQueueOptions = {}) {
        this.maxInFlight = options.maxInFlight ?? 2
        this.itemFloorMs = options.itemFloorMs ?? READ_FLOOR_MS
        this.rateLimitRetryMs = options.rateLimitRetryMs ?? 5_000
        this.defaultPauseMs = options.defaultPauseMs ?? 30_000
        this.requestDeadlineMs = options.requestDeadlineMs ?? 60_000
        this.now = options.now ?? (() => Date.now())
        this.canSpend = options.canSpend ?? canSpend
    }

    enqueue(request: JobRequest): Promise<JobResult> {
        const existing = this.jobs.get(request.key)
        if (existing) {
            existing.groups.add(request.group)
            if (existing.state === 'queued' && MODE_STRENGTH[request.mode] > MODE_STRENGTH[existing.mode]) {
                existing.mode = request.mode
            }
            this.notify()
            return existing.promise
        }
        const sentAt = this.lastSent.get(request.key)
        if (!request.userRetry && sentAt !== undefined && this.now() - sentAt < this.itemFloorMs) {
            return Promise.resolve({ status: 'skipped', computed: false, forced: false, family: request.family })
        }
        let resolve: (result: JobResult) => void = () => undefined
        const promise = new Promise<JobResult>((done) => {
            resolve = done
        })
        const job: Job = {
            key: request.key,
            family: request.family,
            mode: request.mode,
            run: request.run,
            groups: new Set([request.group]),
            state: 'queued',
            retried: false,
            controller: null,
            timer: null,
            promise,
            resolve,
        }
        this.jobs.set(job.key, job)
        this.queue.push(job)
        this.notify()
        this.pump()
        return promise
    }

    /**
     * Drops the queued jobs that only this screen wanted. A running read goes on: the server finishes a started compute
     * anyway, so the answer still fills the cache, its minute floor holds, and a screen that comes back joins it or
     * finds the result instead of sending the same compute again. It also keeps its in-flight slot, so the app never
     * has more than 2 computes running on the server.
     */
    leave(group: string): void {
        for (const job of [...this.jobs.values()]) {
            if (!job.groups.delete(group) || job.groups.size > 0 || job.state === 'running') {
                continue
            }
            this.finish(job, 'aborted', false)
        }
        this.notify()
    }

    /** True while a job of this screen is queued, running, or waiting for its retry. */
    isBusy(group: string): boolean {
        for (const job of this.jobs.values()) {
            if (job.groups.has(group)) {
                return true
            }
        }
        return false
    }

    /** True while a request for this freshness key is queued, running, or waiting for its retry. */
    isKeyBusy(key: string): boolean {
        return this.jobs.has(key)
    }

    subscribe(listener: () => void): () => void {
        this.listeners.add(listener)
        return () => {
            this.listeners.delete(listener)
        }
    }

    familyPausedUntil(family: BudgetFamily): number | null {
        const until = this.pausedUntil.get(family)
        return until !== undefined && until > this.now() ? until : null
    }

    /** Pauses the family after a 429 or 503, for `Retry-After` or 30 s. Other errors change nothing. */
    notePause(family: BudgetFamily, error: unknown): void {
        if (error instanceof ApiError && (error.status === 429 || error.status === 503)) {
            const pauseMs = error.retryAfterSeconds !== undefined ? error.retryAfterSeconds * 1000 : this.defaultPauseMs
            this.pausedUntil.set(family, Math.max(this.pausedUntil.get(family) ?? 0, this.now() + pauseMs))
            this.notify()
            this.pump()
        }
    }

    /** Resolves once the family is not paused. Rejects with an `AbortError` when the signal aborts first. */
    async whenFamilyReady(family: BudgetFamily, signal?: AbortSignal): Promise<void> {
        for (let until = this.familyPausedUntil(family); until !== null; until = this.familyPausedUntil(family)) {
            await sleep(until - this.now(), signal)
        }
    }

    /** Aborts everything and forgets every floor and pause, for the end of a session. */
    reset(): void {
        for (const job of [...this.jobs.values()]) {
            job.groups.clear()
            if (job.state === 'running') {
                job.controller?.abort()
            } else {
                this.finish(job, 'aborted', false)
            }
        }
        this.lastSent.clear()
        this.pausedUntil.clear()
        if (this.pauseTimer) {
            clearTimeout(this.pauseTimer)
            this.pauseTimer = null
        }
        this.pauseTimerUntil = null
        this.notify()
    }

    private notify(): void {
        for (const listener of this.listeners) {
            listener()
        }
    }

    private finish(job: Job, status: JobStatus, computed: boolean): void {
        if (job.timer) {
            clearTimeout(job.timer)
            job.timer = null
        }
        const index = this.queue.indexOf(job)
        if (index >= 0) {
            this.queue.splice(index, 1)
        }
        if (this.jobs.get(job.key) === job) {
            this.jobs.delete(job.key)
        }
        job.resolve({ status, computed, forced: job.mode === 'force_blocking', family: job.family })
        this.notify()
    }

    private pump(): void {
        const now = this.now()
        let waitUntil: number | null = null
        for (const job of [...this.queue]) {
            if (this.running >= this.maxInFlight) {
                break
            }
            const paused = this.pausedUntil.get(job.family)
            if (paused !== undefined && paused > now) {
                waitUntil = waitUntil === null ? paused : Math.min(waitUntil, paused)
                continue
            }
            this.queue.splice(this.queue.indexOf(job), 1)
            if (!this.canSpend(job.family)) {
                this.finish(job, 'capped', false)
                continue
            }
            void this.dispatch(job)
        }
        this.schedulePauseEnd(waitUntil)
    }

    private schedulePauseEnd(until: number | null): void {
        if (this.pauseTimer && this.pauseTimerUntil !== null && (until === null || until < this.pauseTimerUntil)) {
            clearTimeout(this.pauseTimer)
            this.pauseTimer = null
            this.pauseTimerUntil = null
        }
        if (this.pauseTimer || until === null) {
            return
        }
        this.pauseTimerUntil = until
        this.pauseTimer = setTimeout(
            () => {
                this.pauseTimer = null
                this.pauseTimerUntil = null
                this.pump()
            },
            Math.max(0, until - this.now())
        )
    }

    private async dispatch(job: Job): Promise<void> {
        this.running += 1
        job.state = 'running'
        job.controller = new AbortController()
        const controller = job.controller
        this.lastSent.set(job.key, this.now())
        let outcome: { status: JobStatus; computed: boolean } | 'retry'
        let timedOut = false
        let deadlineTimer: ReturnType<typeof setTimeout> | null = null
        try {
            const deadline = new Promise<never>((_resolve, reject) => {
                deadlineTimer = setTimeout(() => {
                    timedOut = true
                    controller.abort()
                    reject(new Error('Views read timed out'))
                }, this.requestDeadlineMs)
            })
            const result = await Promise.race([job.run(job.mode, controller.signal), deadline])
            if (result.status === 'rate_limited' && !job.retried && job.groups.size > 0) {
                outcome = 'retry'
            } else {
                outcome = { status: result.status === 'ok' ? 'ok' : 'failed', computed: result.computed }
            }
        } catch (error) {
            outcome = { status: timedOut ? 'failed' : this.statusForError(job, error), computed: false }
        } finally {
            if (deadlineTimer) {
                clearTimeout(deadlineTimer)
            }
        }
        this.running -= 1
        job.controller = null
        if (outcome === 'retry') {
            this.scheduleRetry(job)
        } else {
            this.finish(job, outcome.status, outcome.computed)
        }
        this.pump()
    }

    private scheduleRetry(job: Job): void {
        job.retried = true
        job.state = 'waiting'
        job.timer = setTimeout(() => {
            job.timer = null
            if (job.groups.size === 0) {
                this.finish(job, 'aborted', false)
                return
            }
            job.state = 'queued'
            this.queue.unshift(job)
            this.pump()
        }, this.rateLimitRetryMs)
    }

    private statusForError(job: Job, error: unknown): JobStatus {
        if (error instanceof Error && error.name === 'AbortError') {
            return 'aborted'
        }
        if (error instanceof BudgetExceededError) {
            return 'capped'
        }
        this.notePause(job.family, error)
        return 'failed'
    }
}

/** The app-wide queue for Views. */
export const viewsQueue = new RefreshQueue()
