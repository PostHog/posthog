// HS256 JWT verification, following the recording-api scheme (PostHog/posthog#67476).
//
// The deployment is established by WHICH KEY VERIFIES the token, never by a claim. So
// there is nothing in the token an attacker could edit to become a different deployment,
// and no need for the token to name one. Trying each deployment's keys in turn is a
// handful of HMAC verifies against a set the size of our pod fleet.
//
// The `caller` claim names the product that wanted the credential. It is NOT verified:
// Django holds one key and hosts many products, so a compromised Django pod could name
// any of them. It is recorded for metrics and audit, collapsed to a constant when we do
// not recognise it, and it grants nothing.
//
// The requested key set travels in the `keys` claim and there is no request body, so a
// token lifted from a log unlocks the fields of one call rather than every credential we
// hold.

import { decodeJwt, jwtVerify } from 'jose'

import { productLabel } from '../products.js'
import type { CallerIdentity } from '../types.js'
import type { SigningKeyLoader } from './registry.js'
import { AUDIENCE, AuthError, type Verifier } from './types.js'

// Caps on the `keys` claim. A holder of a valid signing key would otherwise be able to
// grow this process's memory without bound: every distinct key name becomes a Redis usage
// field, and it is never reclaimed. Revoking a deployment's key bounds what a compromised
// caller can *read*; these bound what it can *cost* before anyone notices.
//
// The real ceiling is the provider manifest, well under 50 fields in total, so no
// legitimate request comes close.
const MAX_REQUESTED_KEYS = 50
const MAX_KEY_LENGTH = 128

function stringArray(value: unknown): string[] | null {
    if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
        return null
    }
    return value as string[]
}

export class JwtVerifier implements Verifier {
    constructor(private readonly keys: SigningKeyLoader) {}

    async verify(token: string): Promise<CallerIdentity> {
        // Decoded only to fail fast on garbage; nothing read here is trusted or used.
        try {
            decodeJwt(token)
        } catch {
            throw new AuthError('malformed', 'token could not be decoded')
        }

        let payload: Record<string, unknown> | null = null
        let deployment = ''
        let sawExpired = false
        let sawBadAudience = false

        outer: for (const [candidate, candidateKeys] of this.keys.entries()) {
            for (const key of candidateKeys) {
                try {
                    const result = await jwtVerify(token, new TextEncoder().encode(key), {
                        algorithms: ['HS256'],
                        audience: AUDIENCE,
                    })
                    payload = result.payload as Record<string, unknown>
                    deployment = candidate
                    break outer
                } catch (err) {
                    const code = (err as { code?: string }).code
                    if (code === 'ERR_JWT_EXPIRED') {
                        sawExpired = true
                    } else if (code === 'ERR_JWT_CLAIM_VALIDATION_FAILED') {
                        sawBadAudience = true
                    }
                }
            }
        }

        if (!payload) {
            if (sawExpired) {
                throw new AuthError('expired', 'token has expired')
            }
            if (sawBadAudience) {
                throw new AuthError('bad_audience', 'token audience does not match')
            }
            throw new AuthError('bad_signature', 'token did not verify against any deployment key')
        }

        const claimedKeys = stringArray(payload['keys'])
        if (!claimedKeys || claimedKeys.length === 0) {
            throw new AuthError('no_keys_claim', 'token carries no keys claim — the request scope is the token')
        }
        if (claimedKeys.length > MAX_REQUESTED_KEYS || claimedKeys.some((key) => key.length > MAX_KEY_LENGTH)) {
            throw new AuthError('oversized_keys_claim', 'keys claim exceeds the per-request limits')
        }

        const claimedProduct = payload['caller']
        return {
            deployment,
            product: productLabel(typeof claimedProduct === 'string' ? claimedProduct : ''),
            // Deduplicate: a repeated key would otherwise be resolved, counted and logged
            // once per occurrence for no benefit.
            requestedKeys: [...new Set(claimedKeys)],
        }
    }
}

/** Pull the bearer token out of an Authorization header. */
export function bearerToken(header: string | undefined): string {
    if (!header || !header.startsWith('Bearer ')) {
        throw new AuthError('missing_token', 'no bearer token')
    }
    const token = header.slice('Bearer '.length).trim()
    if (!token) {
        throw new AuthError('missing_token', 'empty bearer token')
    }
    return token
}
