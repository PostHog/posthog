/**
 * `GET /api/auth/me` — proxy `/oauth/userinfo/` so the UI can show
 * "logged in as X" without ever touching the access token directly.
 *
 * Returns `{ authenticated: false }` for unauthenticated callers
 * rather than 401 — the UI uses this to decide whether to render
 * the login chip vs the user chip.
 */

import { NextResponse } from 'next/server'

import { posthogBaseUrl } from '@/lib/auth/config'
import { clearSession, getSession, setSession, type SessionPayload } from '@/lib/auth/session'
import { OAuthTokenError, refreshAccessToken } from '@/lib/auth/tokens'

/**
 * `GET /api/auth/me` — returns the authenticated identity for the UI.
 *
 * Combines OIDC `/oauth/userinfo/` (sub, email, name) with PostHog's
 * `/api/users/@me/` (the rich user profile + current team). The team
 * is also stamped onto the sealed session cookie at callback time so
 * downstream API calls can scope by it without re-fetching.
 *
 * If the access token has expired (upstream returns 401) we refresh +
 * retry once. Without this the UI lands on teamId=null after every
 * hour-long idle and shows "no current project" until the user re-logs.
 *
 * Both upstreams are best-effort: we surface partial data rather than
 * 401-bouncing the user when one of them errors.
 */
export async function GET(): Promise<Response> {
    let session = await getSession()
    if (!session) {
        return NextResponse.json({ authenticated: false }, { status: 200 })
    }

    let [oidc, profile] = await Promise.all([
        fetchJson(`${posthogBaseUrl()}/oauth/userinfo/`, session.accessToken),
        fetchJson(`${posthogBaseUrl()}/api/users/@me/`, session.accessToken),
    ])

    // If either upstream 401'd, the access token has expired. Refresh
    // and replay both — the userinfo endpoint also needs the new token.
    if (isAuthError(oidc) || isAuthError(profile)) {
        let refreshed: SessionPayload
        try {
            refreshed = await refreshAccessToken(session.refreshToken)
        } catch (err) {
            if (err instanceof OAuthTokenError && (err.status === 400 || err.status === 401)) {
                await clearSession()
                return NextResponse.json({ authenticated: false }, { status: 200 })
            }
            throw err
        }
        session = { ...session, ...refreshed }
        await setSession(session)
        ;[oidc, profile] = await Promise.all([
            fetchJson(`${posthogBaseUrl()}/oauth/userinfo/`, session.accessToken),
            fetchJson(`${posthogBaseUrl()}/api/users/@me/`, session.accessToken),
        ])
    }

    // Prefer fresh team from /api/users/@me/, fall back to the value stamped
    // onto the cookie at callback time.
    const teamId = extractTeamId(profile) ?? session.teamId ?? null

    return NextResponse.json({
        authenticated: true,
        teamId,
        oidc,
        profile,
        // Surfaced so the browser can link back to the main app (the
        // sidebar's "Back to PostHog" item) without leaking the internal
        // url into client code.
        posthogBaseUrl: posthogBaseUrl(),
    })
}

async function fetchJson(url: string, accessToken: string): Promise<unknown | null> {
    try {
        const res = await fetch(url, {
            headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
        })
        if (!res.ok) {
            return { _error: `${res.status} ${res.statusText}`, _status: res.status, _url: url }
        }
        return await res.json()
    } catch (err) {
        return { _error: err instanceof Error ? err.message : String(err), _url: url }
    }
}

function isAuthError(body: unknown): boolean {
    return !!body && typeof body === 'object' && (body as { _status?: number })._status === 401
}

function extractTeamId(profile: unknown): number | null {
    if (!profile || typeof profile !== 'object') {
        return null
    }
    const p = profile as { team?: { id?: number } | null; current_team?: number | { id?: number } | null }
    if (p.team && typeof p.team === 'object' && typeof p.team.id === 'number') {
        return p.team.id
    }
    if (typeof p.current_team === 'number') {
        return p.current_team
    }
    if (p.current_team && typeof p.current_team === 'object' && typeof p.current_team.id === 'number') {
        return p.current_team.id
    }
    return null
}
