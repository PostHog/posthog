export const AUDIENCE = 'posthog:integration_service'

/** Why a token was rejected. A metric label, so keep the set small and stable. */
export type AuthFailureReason =
    | 'missing_token'
    | 'malformed'
    | 'bad_signature'
    | 'expired'
    | 'no_expiry'
    | 'bad_audience'
    | 'no_keys_claim'

export class AuthError extends Error {
    constructor(
        readonly reason: AuthFailureReason,
        message: string
    ) {
        super(message)
        this.name = 'AuthError'
    }
}

/**
 * Signing keys per deployment, newest first. All are accepted for verification; the
 * deployment signs with the first, so a key rotation is zero-downtime.
 *
 * The deployment a token belongs to is whichever key set verifies it. Nothing in the
 * token asserts it, so it cannot be forged by editing a claim.
 */
export type SigningKeys = Record<string, string[]>
