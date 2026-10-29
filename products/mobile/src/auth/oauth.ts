import { AuthRequest, type AuthSessionResult, makeRedirectUri } from 'expo-auth-session'
import { Platform } from 'react-native'

import { appScheme } from '@/lib/environment'

import type { SessionTokens } from './tokens'

// The grant is not narrowed to one project (no `required_access_level`), so the project switcher can list every
// project the user has. The server drops any scope outside the OAuth application's ceiling, so a scope added here
// also needs adding to that application.
export const OAUTH_SCOPES = [
    'openid',
    'profile',
    'email',
    'user:read',
    'user:write',
    'organization:read',
    'project:read',
    'task:read',
    'task:write',
    'conversation:write',
    'today:read',
    'query:read',
    'dashboard:read',
    'insight:read',
    'file_system_shortcut:write',
    'error_tracking:read',
    'error_tracking:write',
    'session_recording:read',
    'replay_scanner:read',
    'replay_scanner:write',
] as const

const REQUEST_TIMEOUT_MS = 20_000
const REVOKE_TIMEOUT_MS = 5_000

/**
 * `posthog://callback` in store builds, `posthog-dev://callback` and `posthog-preview://callback` in internal builds.
 * Internal schemes belong to separate non-first-party OAuth applications so sign-in requires consent.
 */
export function redirectUri(): string {
    return makeRedirectUri({ scheme: appScheme, path: 'callback' })
}

export type OAuthErrorKind =
    | 'cancelled'
    | 'denied'
    | 'in_progress'
    | 'state_mismatch'
    | 'network'
    | 'rejected'
    | 'missing_scope'
    | 'server'
    | 'session_expired'
    | 'unsupported'

const MESSAGES: Record<OAuthErrorKind, string> = {
    cancelled: 'Sign in was canceled before it finished.',
    denied: "Access wasn't granted. Sign in again and allow access to continue.",
    in_progress: 'A sign-in page is already open. Finish or close it, then try again.',
    state_mismatch: "Sign in couldn't be verified. Try again.",
    network: "Couldn't reach PostHog. Check your connection and try again.",
    rejected: "PostHog didn't accept the sign-in. Try again, and check the host and client ID if it keeps happening.",
    missing_scope: "This app's OAuth registration is missing a permission. Ask an admin to update it.",
    server: 'PostHog had a problem signing you in. Try again in a moment.',
    session_expired: 'Your session ended. Sign in again.',
    unsupported: 'Sign in works in the iOS and Android apps. Open the app to log in.',
}

/** A sign-in or token failure. `message` is user-facing copy; `detail` is the server's own text. */
export class OAuthError extends Error {
    readonly kind: OAuthErrorKind
    readonly detail: string | undefined

    constructor(kind: OAuthErrorKind, detail?: string) {
        super(kind === 'rejected' && detail ? `${MESSAGES.rejected} The server said: ${detail}` : MESSAGES[kind])
        this.name = 'OAuthError'
        this.kind = kind
        this.detail = detail
    }
}

interface TokenResponse {
    access_token: string
    refresh_token?: string
    expires_in?: number
    /** Space-separated. Present whenever the server knows the request's scopes. */
    scope?: string
}

function isTokenResponse(value: unknown): value is TokenResponse {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as Record<string, unknown>).access_token === 'string'
    )
}

function scopesOf(response: TokenResponse): string[] | null {
    return typeof response.scope === 'string' ? response.scope.split(/\s+/).filter(Boolean) : null
}

function toSessionTokens(
    response: TokenResponse,
    previous: { refreshToken: string | null; grantedScopes: string[] | null; requestedScopes: string[] | null }
): SessionTokens {
    return {
        kind: 'oauth',
        accessToken: response.access_token,
        // The server rotates refresh tokens for first-party apps; keep the old one only if it sends none.
        refreshToken: response.refresh_token ?? previous.refreshToken,
        expiresAt: typeof response.expires_in === 'number' ? Date.now() + response.expires_in * 1000 : null,
        // A refresh never widens a grant, so a refresh response without `scope` keeps the scopes of the sign-in.
        grantedScopes: scopesOf(response) ?? previous.grantedScopes,
        requestedScopes: previous.requestedScopes,
    }
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
        return await fetch(url, { ...init, signal: controller.signal })
    } catch (error) {
        throw new OAuthError('network', error instanceof Error ? error.message : undefined)
    } finally {
        clearTimeout(timer)
    }
}

async function readOAuthError(response: Response): Promise<{ error?: string; description?: string }> {
    try {
        const body = (await response.json()) as Record<string, unknown>
        return {
            error: typeof body.error === 'string' ? body.error : undefined,
            description: typeof body.error_description === 'string' ? body.error_description : undefined,
        }
    } catch {
        return {}
    }
}

async function postToken(host: string, body: Record<string, string>): Promise<Response> {
    return fetchWithTimeout(
        `${host}/oauth/token`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify(body),
        },
        REQUEST_TIMEOUT_MS
    )
}

function authResultError(result: AuthSessionResult): OAuthError {
    if (result.type === 'cancel' || result.type === 'dismiss') {
        return new OAuthError('cancelled')
    }
    if (result.type === 'locked') {
        return new OAuthError('in_progress')
    }
    if (result.type === 'error') {
        const code = result.error?.code ?? result.params.error
        const detail = result.error?.description ?? result.params.error_description
        if (code === 'state_mismatch') {
            return new OAuthError('state_mismatch')
        }
        if (code === 'access_denied') {
            return new OAuthError('denied', detail)
        }
        if (code === 'invalid_scope') {
            return new OAuthError('missing_scope', detail)
        }
        return new OAuthError('rejected', detail ?? code ?? undefined)
    }
    return new OAuthError('rejected', 'The sign-in page returned no authorization code.')
}

export async function authorize({ host, clientId }: { host: string; clientId: string }): Promise<SessionTokens> {
    if (Platform.OS === 'web') {
        throw new OAuthError('unsupported')
    }
    const request = new AuthRequest({
        clientId,
        redirectUri: redirectUri(),
        scopes: [...OAUTH_SCOPES],
        usePKCE: true,
    })
    let result: AuthSessionResult
    try {
        result = await request.promptAsync({ authorizationEndpoint: `${host}/oauth/authorize` })
    } catch (error) {
        throw new OAuthError('network', error instanceof Error ? error.message : undefined)
    }
    // `promptAsync` compares the returned state with the one it sent and reports a mismatch as an error.
    const code = result.type === 'success' ? result.params.code : undefined
    if (!code) {
        throw authResultError(result)
    }
    if (!request.codeVerifier) {
        throw new OAuthError('rejected', 'The sign-in request lost its PKCE verifier.')
    }
    const response = await postToken(host, {
        grant_type: 'authorization_code',
        code,
        redirect_uri: request.redirectUri,
        client_id: clientId,
        code_verifier: request.codeVerifier,
    })
    if (!response.ok) {
        const { error, description } = await readOAuthError(response)
        if (error === 'invalid_scope') {
            throw new OAuthError('missing_scope', description)
        }
        throw new OAuthError(response.status >= 500 ? 'server' : 'rejected', description ?? error)
    }
    const body: unknown = await response.json()
    if (!isTokenResponse(body)) {
        throw new OAuthError('rejected', 'The token response had no access token.')
    }
    return toSessionTokens(body, { refreshToken: null, grantedScopes: null, requestedScopes: [...OAUTH_SCOPES] })
}

// The server rotates the refresh token on every call and revokes the whole family when an old one is reused after a
// short grace period, so callers must store the result before the next refresh.
export async function refreshTokens({
    host,
    clientId,
    refreshToken,
    grantedScopes = null,
    requestedScopes = null,
}: {
    host: string
    clientId: string
    refreshToken: string
    grantedScopes?: string[] | null
    requestedScopes?: string[] | null
}): Promise<SessionTokens> {
    const response = await postToken(host, {
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: clientId,
    })
    if (response.status === 400 || response.status === 401 || response.status === 403) {
        const { error, description } = await readOAuthError(response)
        throw new OAuthError('session_expired', description ?? error)
    }
    if (!response.ok) {
        throw new OAuthError(
            response.status >= 500 ? 'server' : 'rejected',
            `Token refresh failed with ${response.status}`
        )
    }
    const body: unknown = await response.json()
    if (!isTokenResponse(body)) {
        throw new OAuthError('rejected', 'The token response had no access token.')
    }
    return toSessionTokens(body, { refreshToken, grantedScopes, requestedScopes })
}

// Revocation follows RFC 7009, which takes a form body. Failures are ignored because sign out must work offline.
export async function revokeToken({
    host,
    clientId,
    token,
}: {
    host: string
    clientId: string
    token: string
}): Promise<void> {
    const body = new URLSearchParams({ token, token_type_hint: 'refresh_token', client_id: clientId }).toString()
    try {
        await fetchWithTimeout(
            `${host}/oauth/revoke`,
            { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body },
            REVOKE_TIMEOUT_MS
        )
    } catch {
        // The token expires on its own; the device has already forgotten it.
    }
}
