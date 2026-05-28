/**
 * Typed errors for the v2026 pipeline.
 *
 * Two layers:
 *   1. `RequestStateError` family — internal codec failures. The dispatcher
 *      catches these and maps them to JSON-RPC error responses.
 *   2. `V2026ProtocolError` — JSON-RPC error envelope with the spec-defined
 *      codes (`-32003` MISSING_REQUIRED_CLIENT_CAPABILITY,
 *      `-32004` UNSUPPORTED_PROTOCOL_VERSION) and HTTP status hints.
 */

/** JSON-RPC error codes defined by SEP-2575. */
export const JSON_RPC_ERROR = {
    INVALID_PARAMS: -32602,
    MISSING_REQUIRED_CLIENT_CAPABILITY: -32003,
    UNSUPPORTED_PROTOCOL_VERSION: -32004,
} as const

/** Base class for every `requestState` decode failure. */
export abstract class RequestStateError extends Error {
    /** Short identifier used as a Prometheus metric label. */
    abstract readonly metricLabel: string
    constructor(message: string) {
        super(message)
        this.name = this.constructor.name
    }
}

export class RequestStateMalformed extends RequestStateError {
    readonly metricLabel = 'malformed'
}
export class RequestStateSignatureInvalid extends RequestStateError {
    readonly metricLabel = 'bad_signature'
}
export class RequestStateExpired extends RequestStateError {
    readonly metricLabel = 'expired'
}
export class RequestStateUserMismatch extends RequestStateError {
    readonly metricLabel = 'user_mismatch'
}
export class RequestStateToolMismatch extends RequestStateError {
    readonly metricLabel = 'tool_mismatch'
}
export class RequestStateRoundsExceeded extends RequestStateError {
    readonly metricLabel = 'rounds_exceeded'
}

/**
 * Errors that bubble up as JSON-RPC error envelopes with a specific HTTP
 * status. The dispatcher serializes these directly.
 */
export class V2026ProtocolError extends Error {
    constructor(
        readonly code: number,
        message: string,
        readonly httpStatus: number,
        readonly data?: Record<string, unknown>
    ) {
        super(message)
        this.name = 'V2026ProtocolError'
    }
}

export function unsupportedProtocolVersion(requested: string, supported: string[]): V2026ProtocolError {
    return new V2026ProtocolError(
        JSON_RPC_ERROR.UNSUPPORTED_PROTOCOL_VERSION,
        `Unsupported protocol version: ${requested}`,
        400,
        { requested, supported }
    )
}

export function invalidParams(message: string, data?: Record<string, unknown>): V2026ProtocolError {
    return new V2026ProtocolError(JSON_RPC_ERROR.INVALID_PARAMS, message, 400, data)
}

export function missingRequiredClientCapability(requiredCapabilities: unknown): V2026ProtocolError {
    return new V2026ProtocolError(
        JSON_RPC_ERROR.MISSING_REQUIRED_CLIENT_CAPABILITY,
        'Missing required client capability',
        400,
        { requiredCapabilities }
    )
}
