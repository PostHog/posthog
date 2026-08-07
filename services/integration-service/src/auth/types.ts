// Auth seam.
//
// Phase 1 verifies a per-caller HS256 JWT. The interface exists so a Kubernetes
// projected-ServiceAccount-token verifier (TokenReview) can drop in later as a second
// implementation without touching the routes or the policy layer — that would remove
// the last long-lived secret from caller pods.

import type { CallerIdentity } from '../types.js'

export const AUDIENCE = 'posthog:integration_service'

/** Why a token was rejected. Metric label — keep the set small and stable. */
export type AuthFailureReason =
    | 'missing_token'
    | 'malformed'
    | 'unknown_caller'
    | 'bad_signature'
    | 'expired'
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

/** One caller's entry in the client registry. */
export interface ClientRegistryEntry {
    /**
     * Signing keys, newest first. All are accepted for verification; the caller signs
     * with the first. Same `new,old` convention as RECORDING_API_JWT_SECRET, which is
     * what makes key rotation zero-downtime.
     */
    keys: string[]
    /** Providers this caller may ever obtain — the standing ceiling on a compromised pod. */
    providers: string[]
}

export type ClientRegistry = Record<string, ClientRegistryEntry>
