/**
 * Test-side auth helpers. Most existing cases want "this PAT is valid,
 * this internal secret is valid, this shared secret is valid" with no
 * external Django; this module gives them a stub provider + matching
 * spec snippets so the migration to the new multi-mode shape stays a
 * one-liner per test.
 */

import {
    type AuthProvider,
    type AuthVerifier,
    type VerifyResult,
    publicVerifier,
    readBearer,
} from '@posthog/agent-ingress'
import type { CredentialMap, SessionPrincipal } from '@posthog/agent-shared'

export interface FakeTokens {
    /** Bearer that resolves to a posthog user (oauth + pat modes). */
    pat?: string
    /** x-posthog-internal value. */
    internal?: string
    /** Shared-secret value (in the header named per spec). */
    shared?: string
}

/**
 * Build the standard fixture auth provider — accepts whichever tokens
 * the caller specifies. Returns a posthog user principal for PAT/OAuth,
 * internal/shared_secret principals for the others.
 */
export function fakeAuthProvider(opts: FakeTokens & { teamId?: number; userId?: string } = {}): AuthProvider {
    const teamId = opts.teamId ?? 1
    const userId = opts.userId ?? 'user-1'

    const okPosthog = (source: 'oauth' | 'pat'): VerifyResult => ({
        ok: true,
        principal: { kind: 'posthog', source, user_id: userId, team_id: teamId, email: `${userId}@test` },
        credentials: { posthog_api: { kind: `${source}_bearer`, token: opts.pat ?? '' } } as CredentialMap,
    })

    const verifiers: AuthVerifier[] = [publicVerifier]

    if (opts.pat) {
        // Both oauth + pat verifiers route through the same fake — the
        // discriminator is which mode the spec lists. Tests can mark a
        // spec as oauth or pat; either resolves the same token.
        const verifier = (modeType: 'oauth' | 'pat'): AuthVerifier => ({
            modeType,
            async verify(req) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (bearer !== opts.pat) {
                    return { ok: false, status: 401, reason: 'invalid_token' }
                }
                return okPosthog(modeType)
            },
        })
        verifiers.push(verifier('oauth'), verifier('pat'))
    }

    if (opts.internal) {
        verifiers.push({
            modeType: 'posthog_internal',
            async verify(req) {
                const header = req.headers['x-posthog-internal']
                if (typeof header !== 'string') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (header !== opts.internal) {
                    return { ok: false, status: 403, reason: 'invalid_internal_header' }
                }
                const principal: SessionPrincipal = { kind: 'posthog_internal', team_id: teamId }
                return { ok: true, principal, credentials: {} }
            },
        })
    }

    if (opts.shared) {
        verifiers.push({
            modeType: 'shared_secret',
            async verify(req, mode) {
                if (mode.type !== 'shared_secret') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                const value = req.headers[mode.header.toLowerCase()]
                if (typeof value !== 'string') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (value !== opts.shared) {
                    return { ok: false, status: 401, reason: 'invalid_secret' }
                }
                const principal: SessionPrincipal = { kind: 'shared_secret', team_id: teamId }
                return { ok: true, principal, credentials: {} }
            },
        })
    }

    return { verifiers }
}
