/**
 * Built-in auth verifier impls. The orchestrator in `auth.ts` picks one
 * per request based on `spec.auth.modes`. Verifiers are stateless;
 * external dependencies (HTTP introspect, secret lookup) come in via
 * factory args so tests can inject fakes.
 *
 * Two verifiers cover the PostHog identity path:
 *
 *   - `oauthVerifier` — accepts OAuth bearer tokens
 *   - `patVerifier`   — accepts PostHog Personal API keys
 *
 * Both call the same `PosthogIdentityIntrospector` (default:
 * `/api/users/@me/` against a configurable base URL); PostHog accepts
 * either token type there. The verifier just labels the produced
 * principal + credential differently so audit logs distinguish.
 */

import { Request } from 'express'
import { createHmac, timingSafeEqual } from 'node:crypto'

import { AgentApplication, AuthMode, CredentialMap, SessionPrincipal } from '@posthog/agent-shared'

import { AuthVerifier, publicVerifier, readBearer, VerifyResult } from './auth'

/**
 * Shape returned by PostHog's `/api/users/@me/`. We only depend on the
 * stable fields here so a serializer change in PostHog doesn't break
 * the verifier.
 */
export interface PosthogMeResponse {
    uuid: string
    email: string
    organization?: { id?: string; name?: string }
    team?: { id: number; name?: string; uuid?: string }
    is_staff?: boolean
}

/**
 * The thing that takes a bearer and returns the PostHog user identity.
 * Default impl hits `/api/users/@me/`; tests inject a fake to avoid
 * standing up Django.
 */
export interface PosthogIdentityIntrospector {
    introspect(bearer: string): Promise<PosthogMeResponse | null>
}

export interface DefaultIntrospectorOpts {
    /** Base URL for the PostHog API. Default: `http://localhost:8010`. */
    baseUrl?: string
    /** Optional override for `fetch` — tests inject. */
    fetchImpl?: typeof fetch
}

export function defaultPosthogIntrospector(opts: DefaultIntrospectorOpts = {}): PosthogIdentityIntrospector {
    const baseUrl = (opts.baseUrl ?? 'http://localhost:8010').replace(/\/+$/, '')
    const f = opts.fetchImpl ?? fetch
    return {
        async introspect(bearer: string): Promise<PosthogMeResponse | null> {
            const res = await f(`${baseUrl}/api/users/@me/`, {
                headers: { Authorization: `Bearer ${bearer}`, Accept: 'application/json' },
            })
            if (res.status === 401 || res.status === 403) {
                return null
            }
            if (!res.ok) {
                // Network / 5xx — treat as "couldn't verify", same as invalid.
                return null
            }
            return (await res.json()) as PosthogMeResponse
        },
    }
}

function posthogPrincipalFrom(me: PosthogMeResponse, source: 'oauth' | 'pat'): SessionPrincipal {
    return {
        kind: 'posthog',
        source,
        user_id: me.uuid,
        user_uuid: me.uuid,
        team_id: me.team?.id ?? 0,
        email: me.email,
    }
}

function makePosthogBearerVerifier(opts: {
    type: 'oauth' | 'pat'
    introspector: PosthogIdentityIntrospector
}): AuthVerifier {
    return {
        modeType: opts.type,
        async verify(req: Request, _mode: AuthMode, _app: AgentApplication): Promise<VerifyResult> {
            const bearer = readBearer(req)
            if (!bearer) {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const me = await opts.introspector.introspect(bearer)
            if (!me) {
                return { ok: false, status: 401, reason: 'invalid_token' }
            }
            const principal = posthogPrincipalFrom(me, opts.type)
            const credentials: CredentialMap = {
                posthog_api:
                    opts.type === 'oauth'
                        ? { kind: 'oauth_bearer', token: bearer }
                        : { kind: 'pat_bearer', token: bearer },
            }
            return { ok: true, principal, credentials }
        },
    }
}

export function oauthVerifier(introspector: PosthogIdentityIntrospector): AuthVerifier {
    return makePosthogBearerVerifier({ type: 'oauth', introspector })
}

export function patVerifier(introspector: PosthogIdentityIntrospector): AuthVerifier {
    return makePosthogBearerVerifier({ type: 'pat', introspector })
}

/**
 * JWT verifier. Signature is HS256 over the encrypted-env secret named
 * by `mode.issuer_secret_ref`. Standard 3-segment compact JWT format.
 *
 * Keeps the implementation deliberately small (no audience checking,
 * no nbf, no key rotation) — the embedding party owns the secret and
 * the claim shape; we just prove possession.
 */
export interface JwtSecretResolver {
    resolve(secretRef: string, application: AgentApplication): Promise<string | null>
}

export function jwtVerifier(resolver: JwtSecretResolver): AuthVerifier {
    return {
        modeType: 'jwt',
        async verify(req: Request, mode: AuthMode, application: AgentApplication): Promise<VerifyResult> {
            if (mode.type !== 'jwt') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const bearer = readBearer(req)
            if (!bearer) {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const segments = bearer.split('.')
            if (segments.length !== 3) {
                return { ok: false, status: 401, reason: 'malformed_jwt' }
            }
            const [headerB64, payloadB64, sigB64] = segments
            const secret = await resolver.resolve(mode.issuer_secret_ref, application)
            if (!secret) {
                return { ok: false, status: 500, reason: 'jwt_secret_not_set' }
            }
            const signingInput = `${headerB64}.${payloadB64}`
            const expected = createHmac('sha256', secret).update(signingInput).digest()
            let provided: Buffer
            try {
                provided = Buffer.from(sigB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64')
            } catch {
                return { ok: false, status: 401, reason: 'malformed_jwt_signature' }
            }
            if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
                return { ok: false, status: 401, reason: 'invalid_jwt_signature' }
            }
            let header: { alg?: string }
            let claims: Record<string, unknown>
            try {
                header = JSON.parse(
                    Buffer.from(headerB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString()
                ) as {
                    alg?: string
                }
                claims = JSON.parse(
                    Buffer.from(payloadB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString()
                ) as Record<string, unknown>
            } catch {
                return { ok: false, status: 401, reason: 'malformed_jwt_payload' }
            }
            if (header.alg !== 'HS256') {
                return { ok: false, status: 401, reason: 'unsupported_jwt_alg' }
            }
            const exp = claims.exp
            if (typeof exp === 'number' && exp * 1000 < Date.now()) {
                return { ok: false, status: 401, reason: 'expired_jwt' }
            }
            const sub = claims.sub
            if (typeof sub !== 'string') {
                return { ok: false, status: 401, reason: 'jwt_missing_sub' }
            }
            const principal: SessionPrincipal = {
                kind: 'jwt',
                issuer_secret_ref: mode.issuer_secret_ref,
                sub,
                claims,
            }
            const credentials: CredentialMap = {
                self: { kind: 'jwt', token: bearer, claims },
            }
            return { ok: true, principal, credentials }
        },
    }
}

/**
 * Built-in verifier set with PostHog defaults — what a dev or test
 * harness wires unless it needs to swap something out.
 */
export function buildDefaultVerifiers(opts: {
    introspector: PosthogIdentityIntrospector
    jwtSecretResolver?: JwtSecretResolver
}): AuthVerifier[] {
    const verifiers: AuthVerifier[] = [publicVerifier, oauthVerifier(opts.introspector), patVerifier(opts.introspector)]
    if (opts.jwtSecretResolver) {
        verifiers.push(jwtVerifier(opts.jwtSecretResolver))
    }
    return verifiers
}
