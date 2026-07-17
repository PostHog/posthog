/**
 * OAuth 2.0 authorization-code + PKCE login through the system browser.
 *
 * PostHog Cloud runs a django-oauth-toolkit authorization server with public
 * PKCE clients pre-registered per region (the same client IDs the frontend's
 * standalone OAuth mode uses, see frontend/src/lib/oauth/oauthClient.ts). The
 * flow: open {host}/oauth/authorize in the real browser, receive the code on
 * the local loopback server's /oauth/callback, exchange it at {host}/oauth/token/.
 * Access tokens (pha_...) authenticate the API exactly like personal API keys.
 *
 * This module must stay free of Electron imports so it can be unit tested with
 * plain Node.
 */

import { createHash, randomBytes } from 'node:crypto'

import type { CloudRegion } from '../shared/ipc.ts'

/** Registered public PKCE client IDs per cloud region (none for self-hosted). */
export const OAUTH_CLIENT_IDS: Record<Exclude<CloudRegion, 'custom'>, string> = {
    us: '47rGkjTTMRvkbfU1sdSXsqOGLyJBlbMneRkFKhmO',
    eu: 'VCRpJggenuNKqALWy2Um35S4mHbUcIPPg5hiA03K',
}

/** All scopes, mirroring what an all-access personal API key grants. */
const OAUTH_SCOPE = '*'

/** How long a browser round-trip may take before the flow gives up. */
const FLOW_TIMEOUT_MS = 5 * 60 * 1000

/** Refresh when the access token has less than this long to live. */
export const REFRESH_MARGIN_MS = 60 * 1000

export function oauthClientIdFor(region: CloudRegion): string | null {
    // Override for testing against a self-registered OAuth app (any region)
    if (process.env.POSTHOG_DESKTOP_OAUTH_CLIENT_ID) {
        return process.env.POSTHOG_DESKTOP_OAUTH_CLIENT_ID
    }
    return region === 'custom' ? null : OAUTH_CLIENT_IDS[region]
}

export interface TokenSet {
    accessToken: string
    refreshToken: string
    /** Epoch ms when the access token expires */
    expiresAt: number
}

export function generateCodeVerifier(): string {
    return randomBytes(32).toString('base64url')
}

export function codeChallengeS256(verifier: string): string {
    return createHash('sha256').update(verifier).digest('base64url')
}

export interface AuthorizeUrlParams {
    apiHost: string
    clientId: string
    redirectUri: string
    codeChallenge: string
    state: string
}

export function buildAuthorizeUrl(params: AuthorizeUrlParams): string {
    const url = new URL(`${params.apiHost}/oauth/authorize`)
    url.searchParams.set('client_id', params.clientId)
    url.searchParams.set('redirect_uri', params.redirectUri)
    url.searchParams.set('response_type', 'code')
    url.searchParams.set('code_challenge', params.codeChallenge)
    url.searchParams.set('code_challenge_method', 'S256')
    url.searchParams.set('scope', OAUTH_SCOPE)
    url.searchParams.set('state', params.state)
    return url.toString()
}

interface TokenResponse {
    access_token?: string
    refresh_token?: string
    expires_in?: number
    error?: string
    error_description?: string
}

async function postTokenEndpoint(apiHost: string, body: Record<string, string>): Promise<Response> {
    // Trailing slash matters: /oauth/token 301s to /oauth/token/, and Node's
    // fetch drops the POST body on redirect
    return await fetch(`${apiHost}/oauth/token/`, {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(body).toString(),
        signal: AbortSignal.timeout(15000),
    })
}

function tokenSetFromResponse(data: TokenResponse): TokenSet {
    if (!data.access_token || !data.refresh_token || !data.expires_in) {
        throw new Error('The token response is missing access_token, refresh_token or expires_in')
    }
    return {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + data.expires_in * 1000,
    }
}

export interface ExchangeCodeParams {
    apiHost: string
    clientId: string
    redirectUri: string
    code: string
    codeVerifier: string
}

/** Exchanges the authorization code for tokens. Throws with a user-facing message on failure. */
export async function exchangeCodeForTokens(params: ExchangeCodeParams): Promise<TokenSet> {
    let response: Response
    try {
        response = await postTokenEndpoint(params.apiHost, {
            grant_type: 'authorization_code',
            code: params.code,
            redirect_uri: params.redirectUri,
            client_id: params.clientId,
            code_verifier: params.codeVerifier,
        })
    } catch {
        throw new Error(`Could not reach ${params.apiHost} to complete the sign-in.`)
    }
    const data = (await response.json().catch(() => ({}))) as TokenResponse
    if (!response.ok) {
        throw new Error(data.error_description || data.error || `Token exchange failed (HTTP ${response.status}).`)
    }
    return tokenSetFromResponse(data)
}

export interface RefreshParams {
    apiHost: string
    clientId: string
    refreshToken: string
}

export type RefreshResult =
    | { ok: true; tokens: TokenSet }
    /** terminal: the refresh token was rejected (revoked/expired) — the session is dead.
     *  Non-terminal failures (network, 5xx) must keep the session for a later retry. */
    | { ok: false; terminal: boolean }

export async function refreshAccessToken(params: RefreshParams): Promise<RefreshResult> {
    let response: Response
    try {
        response = await postTokenEndpoint(params.apiHost, {
            grant_type: 'refresh_token',
            refresh_token: params.refreshToken,
            client_id: params.clientId,
        })
    } catch {
        return { ok: false, terminal: false }
    }
    if (!response.ok) {
        return { ok: false, terminal: response.status === 400 || response.status === 401 }
    }
    try {
        return { ok: true, tokens: tokenSetFromResponse((await response.json()) as TokenResponse) }
    } catch {
        return { ok: false, terminal: false }
    }
}

export type FlowResult = { ok: true; tokens: TokenSet } | { ok: false; error: string }

interface PendingFlow {
    state: string
    codeVerifier: string
    apiHost: string
    clientId: string
    redirectUri: string
    resolve: (result: FlowResult) => void
    timer: NodeJS.Timeout
}

/**
 * One in-flight browser sign-in at a time. `begin` hands back the authorize
 * URL to open externally plus a promise that settles when the loopback
 * callback lands (or the flow times out / is superseded).
 */
export class OAuthBrowserFlow {
    private pending: PendingFlow | null = null

    begin(params: { apiHost: string; clientId: string; redirectUri: string }): {
        url: string
        completion: Promise<FlowResult>
    } {
        this.cancel('Sign-in was restarted.')
        const state = randomBytes(16).toString('base64url')
        const codeVerifier = generateCodeVerifier()
        const url = buildAuthorizeUrl({
            apiHost: params.apiHost,
            clientId: params.clientId,
            redirectUri: params.redirectUri,
            codeChallenge: codeChallengeS256(codeVerifier),
            state,
        })
        const completion = new Promise<FlowResult>((resolve) => {
            const timer = setTimeout(() => {
                this.pending = null
                resolve({ ok: false, error: 'The browser sign-in timed out. Try again.' })
            }, FLOW_TIMEOUT_MS)
            timer.unref?.()
            this.pending = { state, codeVerifier, resolve, timer, ...params }
        })
        return { url, completion }
    }

    cancel(reason: string): void {
        if (this.pending) {
            clearTimeout(this.pending.timer)
            this.pending.resolve({ ok: false, error: reason })
            this.pending = null
        }
    }

    /**
     * Handles the loopback redirect from the browser. Returns the message to
     * render in the browser tab; the app-side outcome flows through the
     * `completion` promise from `begin`.
     */
    async handleCallback(query: URLSearchParams): Promise<{ ok: boolean; message: string }> {
        const pending = this.pending
        if (!pending) {
            return { ok: false, message: 'No sign-in is in progress. Start again from the PostHog app.' }
        }
        if (query.get('state') !== pending.state) {
            // Not resolved: a forged or stale callback must not kill the real flow
            return { ok: false, message: 'This sign-in link is stale or invalid. Start again from the PostHog app.' }
        }
        this.pending = null
        clearTimeout(pending.timer)

        const error = query.get('error')
        const code = query.get('code')
        if (error || !code) {
            const message = query.get('error_description') || error || 'The sign-in was denied.'
            pending.resolve({ ok: false, error: message })
            return { ok: false, message }
        }
        try {
            const tokens = await exchangeCodeForTokens({
                apiHost: pending.apiHost,
                clientId: pending.clientId,
                redirectUri: pending.redirectUri,
                code,
                codeVerifier: pending.codeVerifier,
            })
            pending.resolve({ ok: true, tokens })
            return { ok: true, message: 'You are signed in. You can close this tab and return to the PostHog app.' }
        } catch (exchangeError) {
            const message = exchangeError instanceof Error ? exchangeError.message : 'Token exchange failed.'
            pending.resolve({ ok: false, error: message })
            return { ok: false, message }
        }
    }
}
