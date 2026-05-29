/**
 * `GET /api/auth/login` — start the OAuth flow.
 *
 * Generates a fresh `state` (CSRF) + PKCE `code_verifier`, stashes both
 * (plus the return URL) in a short-lived sealed cookie, then redirects
 * the browser to PostHog's `/oauth/authorize`. The `/callback` route
 * pops the cookie back off to exchange the code.
 *
 * Query params:
 *   `returnTo` — relative path to send the user to after login.
 *                Defaults to `/`. External URLs are ignored as a
 *                tiny safety measure against open-redirect tricks.
 */

import { NextResponse } from 'next/server'
import { createHash, randomBytes } from 'node:crypto'

import { clientScope, getOAuthClient, redirectUri } from '@/lib/auth/client'
import { posthogBaseUrl } from '@/lib/auth/config'
import { setOAuthFlow } from '@/lib/auth/session'

function base64url(buf: Buffer): string {
    return buf.toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
}

function safeReturnTo(input: string | null): string {
    if (!input || !input.startsWith('/') || input.startsWith('//')) {
        return '/'
    }
    return input
}

export async function GET(request: Request): Promise<Response> {
    const url = new URL(request.url)
    const returnTo = safeReturnTo(url.searchParams.get('returnTo'))

    const state = base64url(randomBytes(16))
    const codeVerifier = base64url(randomBytes(32))
    const codeChallenge = base64url(createHash('sha256').update(codeVerifier).digest())

    await setOAuthFlow({ state, codeVerifier, returnTo })

    const { clientId } = getOAuthClient()
    const authorizeUrl = new URL('/oauth/authorize/', posthogBaseUrl())
    authorizeUrl.searchParams.set('client_id', clientId)
    authorizeUrl.searchParams.set('redirect_uri', redirectUri())
    authorizeUrl.searchParams.set('response_type', 'code')
    authorizeUrl.searchParams.set('scope', clientScope())
    authorizeUrl.searchParams.set('state', state)
    authorizeUrl.searchParams.set('code_challenge', codeChallenge)
    authorizeUrl.searchParams.set('code_challenge_method', 'S256')

    return NextResponse.redirect(authorizeUrl.toString(), { status: 302 })
}
