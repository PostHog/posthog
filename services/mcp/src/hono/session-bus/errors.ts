/**
 * Errors thrown by the SessionResponseBus and its consumers.
 *
 * Every error in this module is a structured failure of a cross-pod
 * server-initiated request/response correlation. Callers should branch on
 * these classes rather than parsing messages.
 */

export class SessionBusTimeoutError extends Error {
    constructor(sessionId: string, requestId: string | number, timeoutMs: number) {
        super(
            `No response for session=${sessionId} request=${requestId} within ${timeoutMs}ms. ` +
                `The client may have closed the modal without acting, or never received the request.`
        )
        this.name = 'SessionBusTimeoutError'
    }
}

export class SessionBusAbortedError extends Error {
    constructor(reason: string) {
        super(`Session bus await was aborted: ${reason}`)
        this.name = 'SessionBusAbortedError'
    }
}

export class SessionBusUnhealthyError extends Error {
    constructor(message: string, options?: { cause?: unknown }) {
        super(message)
        this.name = 'SessionBusUnhealthyError'
        if (options?.cause !== undefined) {
            // Manual assignment for compatibility with TS libs that don't expose
            // the ES2022 `Error(msg, { cause })` constructor overload.
            ;(this as Error & { cause?: unknown }).cause = options.cause
        }
    }
}
