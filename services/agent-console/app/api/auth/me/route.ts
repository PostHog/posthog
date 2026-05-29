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
import { getSession } from '@/lib/auth/session'

export async function GET(): Promise<Response> {
    const session = await getSession()
    if (!session) {
        return NextResponse.json({ authenticated: false }, { status: 200 })
    }
    const res = await fetch(`${posthogBaseUrl()}/oauth/userinfo/`, {
        headers: { Authorization: `Bearer ${session.accessToken}`, Accept: 'application/json' },
    })
    if (!res.ok) {
        return NextResponse.json(
            { authenticated: false, error: `userinfo ${res.status}`, teamId: session.teamId ?? null },
            { status: 200 }
        )
    }
    const userinfo = await res.json()
    return NextResponse.json({ authenticated: true, teamId: session.teamId ?? null, ...userinfo })
}
