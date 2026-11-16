// The error model of `/v1/integrations/*`: `{error: {code, message, details}}`. Each code maps to
// one exception in the Python SDK, so keep the set stable.

export type IntegrationErrorCode =
    | 'not_found'
    | 'conflict'
    | 'version_mismatch'
    | 'forbidden_op'
    | 'forbidden_kind'
    | 'unsupported_auth_type'
    | 'unreadable_secret'
    | 'validation'
    | 'kms_unavailable'

export type ErrorStatus = 400 | 403 | 404 | 409 | 412 | 422 | 503

const STATUS: Readonly<Record<IntegrationErrorCode, ErrorStatus>> = {
    validation: 400,
    forbidden_op: 403,
    forbidden_kind: 403,
    not_found: 404,
    conflict: 409,
    version_mismatch: 412,
    unsupported_auth_type: 422,
    unreadable_secret: 422,
    kms_unavailable: 503,
}

export class IntegrationApiError extends Error {
    constructor(
        readonly code: IntegrationErrorCode,
        message: string,
        /** Shown to the caller. Never put a secret value here. */
        readonly details: Record<string, unknown> = {}
    ) {
        super(message)
        this.name = 'IntegrationApiError'
    }

    get status(): ErrorStatus {
        return STATUS[this.code]
    }

    body(): { error: { code: IntegrationErrorCode; message: string; details: Record<string, unknown> } } {
        return { error: { code: this.code, message: this.message, details: this.details } }
    }
}

/** The same answer for a row that does not exist and a row of another team, so ids cannot be probed. */
export function notFound(ref: string): IntegrationApiError {
    return new IntegrationApiError('not_found', 'integration not found', { ref })
}
