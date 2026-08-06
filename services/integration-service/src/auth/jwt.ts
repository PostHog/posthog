// HS256 JWT verification, following the recording-api scheme (PostHog/posthog#67476).
//
// Two properties are doing the security work here, and they bound different things:
//
//   - The signing key is PER CALLER, not fleet-wide. So the `caller` claim is
//     authenticated rather than merely asserted: a token is only accepted if it
//     verifies against that caller's own key set. A key leaked from the warehouse
//     worker cannot mint a token claiming to be Django and inherit Django's wider
//     allowlist. This bounds a compromised caller.
//
//   - The requested key set travels in the `keys` claim, and there is NO request body.
//     A token lifted from a log, a trace or an error report unlocks only the fields
//     that one request needed, for five minutes. This bounds a leaked token.
//
// The optional `previous_used` claim is how a rotation learns whether the old value is
// still needed — see metrics.previousVersionUseTotal. It must be a subset of `keys`,
// so a caller cannot report on fields it did not ask for.

import { decodeJwt, jwtVerify } from 'jose'

import type { CallerIdentity } from '../types.js'
import type { ClientRegistryLoader } from './registry.js'
import { AUDIENCE, AuthError, type Verifier } from './types.js'

/** Extra request context a token carries beyond the identity itself. */
export interface TokenExtras {
    /** Keys the caller reports only worked against the third party via the previous value. */
    previousUsed: readonly string[]
}

export interface VerifiedToken {
    identity: CallerIdentity
    extras: TokenExtras
}

function stringArray(value: unknown): string[] | null {
    if (!Array.isArray(value)) {
        return null
    }
    if (!value.every((item) => typeof item === 'string')) {
        return null
    }
    return value as string[]
}

export class JwtVerifier implements Verifier {
    constructor(private readonly registry: ClientRegistryLoader) {}

    async verifyToken(token: string): Promise<VerifiedToken> {
        // Unverified decode, used ONLY to select which key set to verify against. The
        // verification below is what actually authenticates the caller — nothing read
        // here is trusted until jwtVerify has succeeded with that caller's key.
        let unverifiedCaller: string
        try {
            const claims = decodeJwt(token)
            if (typeof claims.caller !== 'string' || claims.caller.length === 0) {
                throw new AuthError('malformed', 'token has no caller claim')
            }
            unverifiedCaller = claims.caller
        } catch (err) {
            if (err instanceof AuthError) {
                throw err
            }
            throw new AuthError('malformed', 'token could not be decoded')
        }

        const entry = this.registry.entryFor(unverifiedCaller)
        if (!entry) {
            throw new AuthError('unknown_caller', `no registry entry for caller ${unverifiedCaller}`)
        }

        // Try every key in the caller's set, newest first, so a rotation window accepts
        // tokens signed with either value.
        let payload: Record<string, unknown> | null = null
        let sawExpired = false
        let sawBadAudience = false

        for (const key of entry.keys) {
            try {
                const result = await jwtVerify(token, new TextEncoder().encode(key), {
                    algorithms: ['HS256'],
                    audience: AUDIENCE,
                })
                payload = result.payload as Record<string, unknown>
                break
            } catch (err) {
                const code = (err as { code?: string }).code
                if (code === 'ERR_JWT_EXPIRED') {
                    sawExpired = true
                } else if (code === 'ERR_JWT_CLAIM_VALIDATION_FAILED') {
                    sawBadAudience = true
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
            throw new AuthError('bad_signature', `token did not verify against any key for ${unverifiedCaller}`)
        }

        // Re-read from the verified payload rather than trusting the earlier decode.
        const caller = payload['caller']
        if (typeof caller !== 'string' || caller !== unverifiedCaller) {
            throw new AuthError('malformed', 'caller claim changed between decode and verify')
        }

        const requestedKeys = stringArray(payload['keys'])
        if (!requestedKeys || requestedKeys.length === 0) {
            throw new AuthError('no_keys_claim', 'token carries no keys claim — the request scope is the token')
        }

        const reportedPreviousUsed = stringArray(payload['previous_used']) ?? []
        const requestedSet = new Set(requestedKeys)

        return {
            identity: {
                caller,
                allowedProviders: new Set(entry.providers),
                requestedKeys,
            },
            extras: {
                // Confine the report to the request's own scope, so a caller cannot
                // hold open somebody else's rotation.
                previousUsed: reportedPreviousUsed.filter((key) => requestedSet.has(key)),
            },
        }
    }

    async verify(token: string): Promise<CallerIdentity> {
        return (await this.verifyToken(token)).identity
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
