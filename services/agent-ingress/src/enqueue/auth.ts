/**
 * Per-trigger auth gate. Reads `spec.auth.modes[]` and walks them in
 * order; the first verifier that matches the incoming request wins.
 *
 * **Identity / credentials split** — the verifier produces:
 *
 *   - `principal: SessionPrincipal` — identity-only, persisted on the
 *     session row (used by ACL + audit log)
 *   - `credentials: CredentialMap` — auth materials (bearer tokens, JWT,
 *     claims) keyed by target — written to the `CredentialBroker` for
 *     tools to query at call time. **Never persisted on the session row
 *     or the principal.**
 *
 * Verifiers per mode:
 *
 *   - `public`             — always succeeds, anonymous principal, no creds
 *   - `oauth` / `pat`      — Authorization: Bearer <token>; verified via
 *                            an `IdentityIntrospector` (PostHog: hit
 *                            `/api/users/@me/`); produces `posthog`
 *                            principal + `posthog_api` credential
 *   - `jwt`                — Authorization: Bearer <jwt>; signature
 *                            verified with the agent's encrypted-env
 *                            secret referenced by `issuer_secret_ref`;
 *                            produces `jwt` principal + `self` credential
 *   - `shared_secret`      — header bearer; matched by per-agent secret
 *   - `posthog_internal`   — x-posthog-internal header; legacy server-to-
 *                            server pathway used by Django ↔ ingress
 *
 * Adding a new mode is two steps: extend `AuthModeSchema` in agent-shared,
 * add a verifier here, register it in `buildDefaultVerifiers`.
 */

import { Request } from 'express'

import {
    AgentApplication,
    AgentSpec,
    AuthMode,
    AuthModeType,
    CredentialMap,
    SessionPrincipal,
} from '@posthog/agent-shared'

/**
 * Strict principal match: same kind + same identifying key. Used on /send
 * and on Slack-thread resumes so "alice's session, bob talking" is
 * rejected at the trigger edge.
 */
export function principalsMatch(stored: SessionPrincipal | null, incoming: SessionPrincipal | null): boolean {
    if (!stored && !incoming) {
        return true
    }
    if (!stored || !incoming) {
        return false
    }
    if (stored.kind !== incoming.kind) {
        return false
    }
    switch (stored.kind) {
        case 'anonymous':
            return true
        case 'posthog':
            return (
                incoming.kind === 'posthog' &&
                stored.user_id === incoming.user_id &&
                stored.team_id === incoming.team_id
            )
        case 'jwt':
            return incoming.kind === 'jwt' && stored.sub === incoming.sub
        case 'slack':
            return (
                incoming.kind === 'slack' &&
                stored.workspace_id === incoming.workspace_id &&
                stored.slack_user_id === incoming.slack_user_id
            )
        case 'posthog_internal':
        case 'shared_secret':
            return incoming.kind === stored.kind && stored.team_id === incoming.team_id
        case 'service':
            return (
                incoming.kind === 'service' &&
                (stored.id != null && incoming.id != null
                    ? stored.id === incoming.id
                    : stored.team_id === incoming.team_id)
            )
    }
}

export interface VerifyOk {
    ok: true
    principal: SessionPrincipal
    credentials: CredentialMap
}
export interface VerifyFail {
    ok: false
    status: number
    reason: string
}
export type VerifyResult = VerifyOk | VerifyFail

/**
 * One verifier per auth mode type. The verifier is responsible for
 * extracting any necessary inputs from `req` (header, body, etc.),
 * cross-checking against the `application` (e.g. team-scoping) +
 * `mode` (mode-specific config), and returning identity + credentials.
 *
 * Verifiers must return `ok: false` for both "no input present" (so
 * fallback to another mode is possible) and "input present but invalid"
 * (auth genuinely failed). The orchestrator distinguishes via status
 * codes: 401/403 are "invalid", anything else is "skip".
 *
 * To allow fallback to the next configured mode on a soft miss
 * (request didn't carry the right header at all), return
 * `{ ok: false, status: 0, reason: 'skip' }`.
 */
export interface AuthVerifier {
    readonly modeType: AuthModeType
    verify(req: Request, mode: AuthMode, application: AgentApplication): Promise<VerifyResult>
}

export interface AuthProvider {
    verifiers: AuthVerifier[]
}

/**
 * Public verifier — always succeeds with the anonymous principal.
 * Order matters: when `public` is listed, every request matches it,
 * so other modes only get a chance if they're listed first.
 */
export const publicVerifier: AuthVerifier = {
    modeType: 'public',
    async verify() {
        return { ok: true, principal: { kind: 'anonymous' }, credentials: {} }
    },
}

/**
 * Default no-op provider. Test harnesses + dev environments should
 * inject a real provider. With no verifiers registered, every auth
 * mode falls through and the trigger 401s — keeping the platform
 * fail-closed by default.
 */
export const PUBLIC_ONLY_AUTH_PROVIDER: AuthProvider = {
    verifiers: [publicVerifier],
}

/**
 * Extract the Bearer token from the Authorization header. Returns null
 * when there's no Authorization header at all (let the caller fall
 * through to the next mode); throws an "invalid bearer" sentinel when
 * the header is present but malformed (auth is genuinely bad).
 */
export function readBearer(req: Request): string | null {
    const header = req.headers['authorization']
    if (typeof header !== 'string') {
        return null
    }
    if (!header.startsWith('Bearer ')) {
        return null
    }
    const token = header.slice('Bearer '.length).trim()
    return token.length > 0 ? token : null
}

/**
 * Walk the spec's configured auth modes; first verifier whose mode is
 * configured AND verifies the request wins. Verifiers return `status: 0`
 * for "no relevant input here, try the next mode"; non-zero failures
 * short-circuit (a present-but-invalid bearer doesn't fall through to
 * the next mode — that'd be a security hole).
 */
export async function authorize(
    req: Request,
    application: AgentApplication,
    spec: AgentSpec,
    provider: AuthProvider
): Promise<VerifyResult> {
    const modes = spec.auth.modes
    if (modes.length === 0) {
        return { ok: false, status: 401, reason: 'no_modes_configured' }
    }
    let firstHardFailure: VerifyFail | null = null
    for (const mode of modes) {
        const verifier = provider.verifiers.find((v) => v.modeType === mode.type)
        if (!verifier) {
            continue
        }
        const result = await verifier.verify(req, mode, application)
        if (result.ok) {
            return result
        }
        // status === 0 means "skip"; anything else is a real failure
        // worth surfacing if no later mode matches.
        if (result.status !== 0 && !firstHardFailure) {
            firstHardFailure = result
        }
    }
    if (firstHardFailure) {
        return firstHardFailure
    }
    return { ok: false, status: 401, reason: 'no_matching_mode' }
}
