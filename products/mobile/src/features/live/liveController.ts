/** What one read brought back. `complete` is false when some of its jobs failed and kept their last value. */
export interface LiveReadResult<T> {
    data: T
    complete: boolean
}

export interface LiveControllerState<T> {
    /** Null until a read brings data. A failed read never clears it. */
    data: T | null
    /** When a read last brought data, epoch milliseconds. */
    updatedAt: number | null
    paused: boolean
    reading: boolean
    /** Reads in a row that failed in whole or in part. Zero after a complete read. */
    failures: number
}

export type LiveControllerEvent = 'background_stopped' | 'foreground_resumed'

export type LiveStatus = 'loading' | 'live' | 'reconnecting' | 'paused'

/** What the status line says. A failed read shows "Reconnecting…" over the last data until a read completes. */
export function liveStatus(state: LiveControllerState<unknown>): LiveStatus {
    if (state.paused) {
        return 'paused'
    }
    if (state.failures > 0) {
        return 'reconnecting'
    }
    return state.data === null ? 'loading' : 'live'
}

export interface LiveSlowdown {
    afterMs: number
    intervalMs: number
}

export interface LiveControllerOptions<T> {
    /** One full read. Rejects only when nothing came back. */
    read: (signal: AbortSignal, previous: T | null) => Promise<LiveReadResult<T>>
    intervalMs: number
    /** How long the app can stay in the background before reads stop, like the web's hidden-tab grace. */
    graceMs: number
    maxBackoffMs: number
    /** After `afterMs` without a user action, reads come every `intervalMs` instead, to stretch the query budget. */
    slowdown?: LiveSlowdown
    onChange: (state: LiveControllerState<T>) => void
    onEvent?: (event: LiveControllerEvent) => void
}

/**
 * Polls while the screen is visible, the app is in the foreground and the user has not paused. Every stop clears the
 * timer and aborts the read in flight, so no read runs for a screen nobody sees. The next read is timed from the end of
 * the last one, so a slow read never overlaps the next.
 */
export class LiveController<T> {
    private state: LiveControllerState<T> = { data: null, updatedAt: null, paused: false, reading: false, failures: 0 }
    private visible = false
    private foreground = true
    private backgroundStopped = false
    private backgroundSince = 0
    private disposed = false
    private timer: ReturnType<typeof setTimeout> | null = null
    private graceTimer: ReturnType<typeof setTimeout> | null = null
    private abort: AbortController | null = null
    private inFlight: Promise<void> | null = null
    /** Bumped by every stop, so a read that settles after it changes nothing. */
    private generation = 0
    private emptyReads = 0
    private activeSince = 0

    constructor(private readonly options: LiveControllerOptions<T>) {}

    get current(): LiveControllerState<T> {
        return this.state
    }

    private get running(): boolean {
        return this.visible && !this.backgroundStopped && !this.state.paused && !this.disposed
    }

    setVisible(visible: boolean): void {
        if (visible === this.visible) {
            return
        }
        this.visible = visible
        if (visible) {
            this.start()
        } else {
            this.stop()
        }
    }

    /** The app came to the foreground or left it. Leaving stops after the grace; coming back reads at once. */
    setForeground(active: boolean): void {
        if (active === this.foreground || this.disposed) {
            return
        }
        this.foreground = active
        if (!active) {
            this.backgroundSince = Date.now()
            this.graceTimer = setTimeout(() => {
                this.graceTimer = null
                this.stopForBackground()
            }, this.options.graceMs)
            return
        }
        if (this.graceTimer !== null) {
            clearTimeout(this.graceTimer)
            this.graceTimer = null
            if (Date.now() - this.backgroundSince < this.options.graceMs) {
                return
            }
            this.stopForBackground()
        }
        if (this.backgroundStopped) {
            this.backgroundStopped = false
            if (this.running) {
                this.options.onEvent?.('foreground_resumed')
                this.start()
            }
        }
    }

    pause(): void {
        if (this.state.paused || this.disposed) {
            return
        }
        this.stop()
        this.update({ paused: true })
    }

    resume(): Promise<void> {
        if (!this.state.paused || this.disposed) {
            return Promise.resolve()
        }
        this.update({ paused: false })
        this.activeSince = Date.now()
        return this.running ? this.readNow() : Promise.resolve()
    }

    /** Reads now, or joins the read in flight. While paused it reads once and stays paused. */
    refresh(): Promise<void> {
        if (this.disposed) {
            return Promise.resolve()
        }
        this.activeSince = Date.now()
        return this.readNow()
    }

    dispose(): void {
        this.stop()
        if (this.graceTimer !== null) {
            clearTimeout(this.graceTimer)
            this.graceTimer = null
        }
        this.disposed = true
    }

    private start(): void {
        if (this.running) {
            this.activeSince = Date.now()
            void this.readNow()
        }
    }

    private stopForBackground(): void {
        const wasRunning = this.running
        this.backgroundStopped = true
        this.stop()
        if (wasRunning) {
            this.options.onEvent?.('background_stopped')
        }
    }

    private stop(): void {
        this.clearTimer()
        this.generation += 1
        this.abort?.abort()
        this.abort = null
        this.inFlight = null
        if (this.state.reading) {
            this.update({ reading: false })
        }
    }

    private readNow(): Promise<void> {
        if (this.inFlight) {
            return this.inFlight
        }
        this.clearTimer()
        const generation = this.generation
        const controller = new AbortController()
        this.abort = controller
        this.update({ reading: true })
        const run = this.options.read(controller.signal, this.state.data).then(
            (result) => {
                if (generation !== this.generation) {
                    return
                }
                this.emptyReads = 0
                this.settle({
                    data: result.data,
                    updatedAt: Date.now(),
                    failures: result.complete ? 0 : this.state.failures + 1,
                })
            },
            () => {
                if (generation !== this.generation) {
                    return
                }
                this.emptyReads += 1
                this.settle({ failures: this.state.failures + 1 })
            }
        )
        this.inFlight = run
        return run
    }

    private settle(patch: Partial<LiveControllerState<T>>): void {
        this.inFlight = null
        this.abort = null
        this.update({ ...patch, reading: false })
        if (!this.running) {
            return
        }
        const slowdown = this.options.slowdown
        const interval =
            slowdown && Date.now() - this.activeSince >= slowdown.afterMs
                ? slowdown.intervalMs
                : this.options.intervalMs
        const delay =
            this.emptyReads === 0
                ? interval
                : Math.min(interval * 2 ** (this.emptyReads - 1), this.options.maxBackoffMs)
        this.timer = setTimeout(() => {
            this.timer = null
            void this.readNow()
        }, delay)
    }

    private clearTimer(): void {
        if (this.timer !== null) {
            clearTimeout(this.timer)
            this.timer = null
        }
    }

    private update(patch: Partial<LiveControllerState<T>>): void {
        this.state = { ...this.state, ...patch }
        this.options.onChange(this.state)
    }
}
