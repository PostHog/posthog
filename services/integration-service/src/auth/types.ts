// Auth seam.
//
// Phase 1 verifies an HS256 JWT signed with a deployment's key. The interface exists so
// a Kubernetes projected-ServiceAccount-token verifier (TokenReview) can drop in later
// as a second implementation without touching the routes or the policy layer — that
// would remove the last long-lived secret from caller pods.

import type { CallerIdentity } from '../types.js'

export const AUDIENCE = 'posthog:integration_service'

/** Why a token was rejected. Metric label — keep the set small and stable. */
export type AuthFailureReason =
    | 'missing_token'
    | 'malformed'
    | 'bad_signature'
    | 'expired'
    | 'no_expiry'
    | 'bad_audience'
    | 'no_keys_claim'
    | 'oversized_keys_claim'

export class AuthError extends Error {
    constructor(
        readonly reason: AuthFailureReason,
        message: string
    ) {
        super(message)
        this.name = 'AuthError'
    }
}

export interface Verifier {
    /** Resolve the bearer token to a verified identity, or throw AuthError. */
    verify(token: string): Promise<CallerIdentity>
}

/**
 * Signing keys per deployment, newest first. All are accepted for verification; the
 * deployment signs with the first, so a key rotation is zero-downtime.
 *
 * The deployment a token belongs to is whichever key set verifies it. Nothing in the
 * token asserts it, so it cannot be forged by editing a claim.
 */
export type SigningKeys = Record<string, string[]>
