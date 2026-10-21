// HS256 JWT verification, following the recording-api scheme (PostHog/posthog#67476).
//
// The deployment is WHICH KEY VERIFIES the token, never a claim, so there is nothing in the
// token an attacker could edit to become a different deployment. The `keys` claim is the
// whole request scope, so a token lifted from a log unlocks one call's fields.

import { jwtVerify } from 'jose'

import type { CallerIdentity } from '../types'
import type { SigningKeyLoader } from './registry'
import { AUDIENCE, AuthError, type AuthFailureReason } from './types'

/**
 * Map a jose failure to a rejection reason, or null when it only means "not this key". Only
 * the key that verifies the signature reaches the claim checks, so at most one is non-null.
 */
function rejectionReason(err: unknown): AuthFailureReason | null {
    const code = (err as { code?: string }).code
    switch (code) {
        case 'ERR_JWS_INVALID':
        case 'ERR_JWT_INVALID':
            return 'malformed'
        case 'ERR_JWT_EXPIRED':
            return 'expired'
        case 'ERR_JWT_CLAIM_VALIDATION_FAILED':
            return (err as { claim?: string }).claim === 'exp' ? 'no_expiry' : 'bad_audience'
        default:
            return null
    }
}

function stringArray(value: unknown): string[] {
    if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
        return []
    }
    return value as string[]
}

export class JwtVerifier {
    constructor(private readonly keys: SigningKeyLoader) {}

    async verify(token: string): Promise<CallerIdentity> {
        let payload: Record<string, unknown> | undefined
        let deployment = ''
        let reason: AuthFailureReason = 'bad_signature'

        outer: for (const [candidate, candidateKeys] of this.keys.entries()) {
            for (const key of candidateKeys) {
                try {
                    const result = await jwtVerify(token, new TextEncoder().encode(key), {
                        algorithms: ['HS256'],
                        audience: AUDIENCE,
                        // jose only checks `exp` when the claim is present, so without this
                        // a token minted without one verifies and never expires.
                        requiredClaims: ['exp'],
                    })
                    payload = result.payload as Record<string, unknown>
                    deployment = candidate
                    break outer
                } catch (err) {
                    reason = rejectionReason(err) ?? reason
                }
            }
        }

        if (!payload) {
            throw new AuthError(reason, 'token was not accepted')
        }

        const requested = stringArray(payload['keys'])
        if (requested.length === 0) {
            throw new AuthError('no_keys_claim', 'token carries no keys claim — the request scope is the token')
        }

        return {
            deployment,
            caller: typeof payload['caller'] === 'string' ? payload['caller'] : '',
            // A repeat would otherwise be resolved, counted and logged once per occurrence.
            requestedKeys: [...new Set(requested)],
        }
    }
}

/** Pull the bearer token out of an Authorization header. */
export function bearerToken(header: string | undefined): string {
    if (!header?.startsWith('Bearer ')) {
        throw new AuthError('missing_token', 'no bearer token')
    }
    const token = header.slice('Bearer '.length).trim()
    if (!token) {
        throw new AuthError('missing_token', 'empty bearer token')
    }
    return token
}
