/**
 * OAuth token exchange + refresh.
 *
 * Both the callback handler (code → tokens) and the catch-all proxy
 * (refresh on 401) live here so the token shape + parsing is in one
 * place.
 *
 * Server-side only.
 */

import { getOAuthClient, redirectUri } from './client'
import { posthogBaseUrl } from './config'
import type { SessionPayload } from './session'

interface TokenResponse {
    access_token: string
    refresh_token: string
    token_type: string
    expires_in: number
    scope: string
    id_token?: string
}

export class OAuthTokenError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
        super(message)
        this.status = status
        this.name = 'OAuthTokenError'
    }
}

export async function exchangeAuthorizationCode(opts: { code: string; codeVerifier: string }): Promise<SessionPayload> {
    const { clientId, clientSecret } = getOAuthClient()
    const body = new URLSearchParams({
        grant_type: 'authorization_code',
        code: opts.code,
        redirect_uri: redirectUri(),
        client_id: clientId,
        client_secret: clientSecret,
        code_verifier: opts.codeVerifier,
    })
    return await tokenRequest(body)
}

export async function refreshAccessToken(refreshToken: string): Promise<SessionPayload> {
    const { clientId, clientSecret } = getOAuthClient()
    const body = new URLSearchParams({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: clientId,
        client_secret: clientSecret,
    })
    return await tokenRequest(body)
}

async function tokenRequest(body: URLSearchParams): Promise<SessionPayload> {
    const res = await fetch(`${posthogBaseUrl()}/oauth/token/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            Accept: 'application/json',
        },
        body: body.toString(),
    })
    if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new OAuthTokenError(res.status, `token endpoint ${res.status}: ${text}`)
    }
    const data = (await res.json()) as TokenResponse
    return {
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        accessTokenExpiresAt: Date.now() + data.expires_in * 1000,
        scope: data.scope,
        sub: parseSubFromIdToken(data.id_token),
    }
}

/** Decode the OIDC `sub` claim from an id_token JWT without verifying.
 *  We trust the token because we just received it over TLS from the
 *  OAuth server; downstream API calls re-validate via the access_token. */
function parseSubFromIdToken(idToken: string | undefined): string | undefined {
    if (!idToken) {
        return undefined
    }
    const parts = idToken.split('.')
    if (parts.length !== 3) {
        return undefined
    }
    try {
        const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8')) as { sub?: string }
        return payload.sub
    } catch {
        return undefined
    }
}
