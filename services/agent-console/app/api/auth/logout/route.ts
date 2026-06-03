/**
 * `POST /api/auth/logout` (also accepts GET for link-driven logout).
 *
 * Revokes both tokens via PostHog's `/oauth/revoke/` endpoint, then
 * clears the session cookie. Best-effort — if revocation fails the
 * cookie still goes away. Redirects to `/` so the user lands on the
 * unauthed sign-in screen instead of bouncing straight back into the
 * OAuth flow.
 */

import { NextResponse } from 'next/server'

import { getOAuthClient } from '@/lib/auth/client'
import { posthogBaseUrl } from '@/lib/auth/config'
import { clearSession, getSession } from '@/lib/auth/session'

async function revoke(token: string, hint: 'access_token' | 'refresh_token'): Promise<void> {
    const { clientId, clientSecret } = getOAuthClient()
    const body = new URLSearchParams({
        token,
        token_type_hint: hint,
        client_id: clientId,
        client_secret: clientSecret,
    })
    try {
        await fetch(`${posthogBaseUrl()}/oauth/revoke/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString(),
        })
    } catch {
        // Best-effort — the cookie still gets cleared.
    }
}

async function handle(): Promise<Response> {
    const session = await getSession()
    if (session) {
        await Promise.all([revoke(session.accessToken, 'access_token'), revoke(session.refreshToken, 'refresh_token')])
    }
    await clearSession()
    return NextResponse.redirect(new URL('/', getOrigin()), { status: 302 })
}

function getOrigin(): string {
    return process.env.CONSOLE_BASE_URL ?? 'http://localhost:3040'
}

export const GET = handle
export const POST = handle
