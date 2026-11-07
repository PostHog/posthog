import { abortError } from '@/lib/abort'

export const REQUEST_TIMEOUT_MS = 30_000

export class TransportError extends Error {
    constructor() {
        super("Couldn't reach PostHog. Check your connection and try again.")
        this.name = 'TransportError'
    }
}

export class RequestTimeoutError extends TransportError {
    constructor() {
        super()
        this.message = 'The request took too long. Try again.'
        this.name = 'RequestTimeoutError'
    }
}

export async function transport<T>(work: () => Promise<T>): Promise<T> {
    try {
        return await work()
    } catch (error) {
        if (error instanceof SyntaxError || (error instanceof Error && error.name === 'AbortError')) {
            throw error
        }
        throw new TransportError()
    }
}

export async function requestWithDeadline<T>(
    work: (signal: AbortSignal) => Promise<T>,
    caller?: AbortSignal | null,
    timeoutMs = REQUEST_TIMEOUT_MS
): Promise<T> {
    if (caller?.aborted) {
        throw abortError()
    }
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let onAbort: () => void = () => undefined
    const cancelled = new Promise<never>((_resolve, reject) => {
        onAbort = () => {
            const error = abortError()
            reject(error)
            controller.abort(error)
        }
        caller?.addEventListener('abort', onAbort, { once: true })
        timer = setTimeout(() => {
            const error = new RequestTimeoutError()
            reject(error)
            controller.abort(error)
        }, timeoutMs)
    })
    try {
        return await Promise.race([work(controller.signal), cancelled])
    } finally {
        clearTimeout(timer)
        caller?.removeEventListener('abort', onAbort)
    }
}
