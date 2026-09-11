import type { DisposablesManager } from '~/kea-disposables'

import type { StoredLogEntry } from '../types/wireTypes'

export type RecoveryPhase = 'bootstrap' | 'stream' | 'history' | 'finalization'

export const STREAM_REQUEST_TIMEOUT_MS = 30_000
export const STREAM_HISTORY_TIMEOUT_MS = 60_000
export const STREAM_IDLE_TIMEOUT_MS = 60_000

export function isTransientStreamError(error: { status?: number; retryable?: boolean }): boolean {
    return (
        error.retryable !== false &&
        (error.status === undefined ||
            error.status === 0 ||
            error.status === 408 ||
            error.status === 429 ||
            (error.status >= 500 && error.status < 600))
    )
}

export class RunStreamRecovery {
    readonly controller = new AbortController()
    phase: RecoveryPhase = 'bootstrap'
    paused = false
    buffering = true
    buffer: StoredLogEntry[] = []
    receivedCursor?: string
    committedCursor?: string
    private resourceId = 0

    constructor(
        readonly projectId: number,
        readonly taskId: string,
        readonly runId: string,
        readonly generation: number,
        private readonly disposables: DisposablesManager,
        private readonly isCurrent: () => boolean
    ) {
        disposables.add(() => () => this.controller.abort(), 'stream-session', { pauseOnPageHidden: false })
    }

    owns(): boolean {
        return !this.controller.signal.aborted && !this.disposables.isDisposed && this.isCurrent()
    }

    check(): void {
        if (!this.owns()) {
            throw new DOMException('Recovery canceled', 'AbortError')
        }
    }

    async request<T>(
        timeoutMs: number,
        request: (signal: AbortSignal) => Promise<T>,
        parent: AbortSignal = this.controller.signal
    ): Promise<T> {
        this.check()
        const key = `stream-request-${this.generation}-${this.resourceId++}`
        const controller = new AbortController()
        let settled = false
        try {
            const result = await new Promise<T>((resolve, reject) => {
                const cancel = (): void => {
                    controller.abort()
                    reject(new DOMException('Recovery canceled', 'AbortError'))
                }
                this.disposables.add(
                    () => {
                        const timer = setTimeout(() => {
                            reject(new DOMException('Agent request timed out', 'TimeoutError'))
                            controller.abort()
                        }, timeoutMs)
                        parent.addEventListener('abort', cancel, { once: true })
                        this.controller.signal.addEventListener('abort', cancel, { once: true })
                        if (parent.aborted) {
                            cancel()
                        } else {
                            request(controller.signal).then(resolve, reject)
                        }
                        return () => {
                            clearTimeout(timer)
                            parent.removeEventListener('abort', cancel)
                            this.controller.signal.removeEventListener('abort', cancel)
                            if (!settled) {
                                cancel()
                            }
                        }
                    },
                    key,
                    { pauseOnPageHidden: false }
                )
            })
            this.check()
            return result
        } finally {
            settled = true
            this.disposables.dispose(key)
        }
    }

    async wait(delayMs: number): Promise<void> {
        this.check()
        const key = `stream-delay-${this.generation}-${this.resourceId++}`
        try {
            await new Promise<void>((resolve, reject) => {
                const cancel = (): void => reject(new DOMException('Recovery canceled', 'AbortError'))
                this.disposables.add(
                    () => {
                        const timer = setTimeout(resolve, delayMs)
                        this.controller.signal.addEventListener('abort', cancel, { once: true })
                        return () => {
                            clearTimeout(timer)
                            this.controller.signal.removeEventListener('abort', cancel)
                            cancel()
                        }
                    },
                    key,
                    { pauseOnPageHidden: false }
                )
            })
            this.check()
        } finally {
            this.disposables.dispose(key)
        }
    }
}
