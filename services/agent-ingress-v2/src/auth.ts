/**
 * Per-trigger auth gate. Reads the agent's spec.auth.mode and applies the
 * matching check. Returns a Principal on success, or null when denied.
 *
 * Modes (mirror the old caller-auth model):
 *   - public            — no check. Principal is { kind: "anonymous" }.
 *   - pat               — Authorization: Bearer <pat>. Validated via the
 *                         injected `AuthProvider.verifyPat`.
 *   - posthog_internal  — x-posthog-internal: <secret>. Validated via the
 *                         injected `AuthProvider.verifyInternal`.
 *   - shared_secret     — <spec.auth.header>: <secret>. Validated via the
 *                         injected `AuthProvider.verifySharedSecret`.
 *
 * The provider is supplied at app-build time. Default: deny everything
 * non-public. Tests supply a provider with known good tokens.
 */

import { Request } from 'express'

import { AgentApplication, AgentSpec } from '@posthog/agent-shared-v2'

export type Principal =
    | { kind: 'anonymous' }
    | { kind: 'service'; team_id: number; pat_id?: string }
    | { kind: 'internal'; team_id: number }
    | { kind: 'shared_secret'; team_id: number }

export interface AuthProvider {
    verifyPat(token: string, application: AgentApplication): Promise<Principal | null>
    verifyInternal(secret: string, application: AgentApplication): Promise<Principal | null>
    verifySharedSecret(secret: string, application: AgentApplication): Promise<Principal | null>
}

export const PUBLIC_ONLY_AUTH_PROVIDER: AuthProvider = {
    async verifyPat() {
        return null
    },
    async verifyInternal() {
        return null
    },
    async verifySharedSecret() {
        return null
    },
}

export async function authorize(
    req: Request,
    application: AgentApplication,
    spec: AgentSpec,
    provider: AuthProvider
): Promise<{ ok: true; principal: Principal } | { ok: false; status: number; reason: string }> {
    const mode = spec.auth.mode
    if (mode === 'public') {
        return { ok: true, principal: { kind: 'anonymous' } }
    }
    if (mode === 'pat') {
        const header = req.headers['authorization']
        if (typeof header !== 'string' || !header.startsWith('Bearer ')) {
            return { ok: false, status: 401, reason: 'missing_token' }
        }
        const token = header.slice('Bearer '.length).trim()
        const principal = await provider.verifyPat(token, application)
        if (!principal) {
            return { ok: false, status: 401, reason: 'invalid_token' }
        }
        return { ok: true, principal }
    }
    if (mode === 'posthog_internal') {
        const header = req.headers['x-posthog-internal']
        if (typeof header !== 'string') {
            return { ok: false, status: 403, reason: 'missing_internal_header' }
        }
        const principal = await provider.verifyInternal(header, application)
        if (!principal) {
            return { ok: false, status: 403, reason: 'invalid_internal_header' }
        }
        return { ok: true, principal }
    }
    if (mode === 'shared_secret') {
        const headerName = spec.auth.header
        if (!headerName) {
            return { ok: false, status: 500, reason: 'shared_secret_misconfigured' }
        }
        const value = req.headers[headerName.toLowerCase()]
        if (typeof value !== 'string') {
            return { ok: false, status: 401, reason: 'missing_secret_header' }
        }
        const principal = await provider.verifySharedSecret(value, application)
        if (!principal) {
            return { ok: false, status: 401, reason: 'invalid_secret' }
        }
        return { ok: true, principal }
    }
    return { ok: false, status: 401, reason: 'unknown_auth_mode' }
}
