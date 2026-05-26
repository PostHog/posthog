/**
 * Errors thrown by the SessionResponseBus and its consumers.
 *
 * Every error in this module is a structured failure of a cross-pod
 * server-initiated request/response correlation. Callers should branch on
 * these classes rather than parsing messages.
 */

export class SessionBusTimeoutError extends Error {
    constructor(requestId: string | number, timeoutMs: number) {
        super(
            `No response for request=${requestId} within ${timeoutMs}ms. ` +
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

/**
 * The client returned a JSON-RPC error response to a server-initiated request
 * (today: `elicitation/create`). This is a *legitimate* protocol signal — the
 * client is telling us it doesn't support the requested operation or rejected
 * it at the protocol layer — not a bus health problem. Distinguishing this
 * from `SessionBusUnhealthyError` lets observability avoid false health
 * incidents and lets tool authors fall back gracefully.
 *
 * Carries the JSON-RPC error code (e.g. `-32601` Method not found, `-32602`
 * for unsupported elicit mode) so callers can branch on it.
 */
export class ElicitationNotSupportedError extends Error {
    readonly code: number

    constructor(code: number, message: string) {
        super(`Client rejected elicitation/create (code=${code}): ${message}`)
        this.name = 'ElicitationNotSupportedError'
        this.code = code
    }
}
