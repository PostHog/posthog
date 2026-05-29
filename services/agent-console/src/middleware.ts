/**
 * Middleware — gate browser page navigations on a session cookie.
 *
 * Runs only for HTML page requests; `/api/*` routes are skipped because
 * the catch-all proxy returns its own 401 (which the browser-side
 * `apiClient` surfaces as an `ApiError`). Skipping `/api/*` also avoids
 * a redirect loop when the very first call is to `/api/auth/login`.
 *
 * Detection is intentionally cookie-presence-only — middleware can't
 * decrypt the sealed cookie (no Node crypto access in the edge
 * runtime), and a stale/expired cookie will surface as a 401 from the
 * proxy on the first API request after navigation, at which point the
 * user is bounced through `/api/auth/login` cleanly.
 */

import { NextResponse, type NextRequest } from 'next/server'

const SESSION_COOKIE = 'agent-console-session'

export function middleware(request: NextRequest): NextResponse {
    const { pathname, search } = request.nextUrl
    if (request.cookies.has(SESSION_COOKIE)) {
        return NextResponse.next()
    }
    const loginUrl = request.nextUrl.clone()
    loginUrl.pathname = '/api/auth/login'
    loginUrl.search = `?returnTo=${encodeURIComponent(pathname + search)}`
    return NextResponse.redirect(loginUrl)
}

export const config = {
    // Skip Next.js internals, static assets, public files, and (most importantly)
    // every `/api/*` route — those handle their own auth.
    matcher: ['/((?!api|_next|favicon.ico|mockServiceWorker.js).*)'],
}
