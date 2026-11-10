// HS256 JWT verification, following the recording-api scheme (PostHog/posthog#67476).
//
// The deployment is WHICH KEY VERIFIES the token, never a claim, so there is nothing in the
// token an attacker could edit to become a different deployment. The `keys` claim is the
// whole request scope, so a token lifted from a log unlocks one call's fields.

import { type JWTPayload, type JWTVerifyOptions, jwtVerify } from 'jose'

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
        case 'ERR_JWT_CLAIM_VALIDATION_FAILED': {
            const claim = (err as { claim?: string }).claim
            if (claim === 'exp') {
                return 'no_expiry'
            }
            return claim === 'aud' ? 'bad_audience' : 'malformed'
        }
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

export interface VerifiedToken {
    /** The deployment whose key verified the signature. */
    deployment: string
    payload: JWTPayload
}

/**
 * Try every deployment's keys in turn and return the payload of the one that verifies.
 * Throws an AuthError when none does.
 *
 * `aud` must equal the expected audience as a plain string. jose accepts an array that
 * merely contains it, so one token could otherwise carry both audiences and be valid at
 * both the secrets and the integrations endpoints.
 */
export async function verifyDeploymentToken(
    keys: SigningKeyLoader,
    token: string,
    options: JWTVerifyOptions & { audience: string }
): Promise<VerifiedToken> {
    let reason: AuthFailureReason = 'bad_signature'

    for (const [deployment, candidateKeys] of keys.entries()) {
        for (const key of candidateKeys) {
            let payload: JWTPayload
            try {
                payload = (
                    await jwtVerify(token, new TextEncoder().encode(key), {
                        ...options,
                        algorithms: ['HS256'],
                        // jose only checks `exp` when the claim is present, so without this
                        // a token minted without one verifies and never expires.
                        requiredClaims: ['exp', ...(options.requiredClaims ?? [])],
                    })
                ).payload
            } catch (err) {
                reason = rejectionReason(err) ?? reason
                continue
            }
            if (payload.aud !== options.audience) {
                throw new AuthError('bad_audience', 'token was not accepted')
            }
            return { deployment, payload }
        }
    }

    throw new AuthError(reason, 'token was not accepted')
}

export class JwtVerifier {
    constructor(private readonly keys: SigningKeyLoader) {}

    async verify(token: string): Promise<CallerIdentity> {
        const { deployment, payload } = await verifyDeploymentToken(this.keys, token, { audience: AUDIENCE })

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
