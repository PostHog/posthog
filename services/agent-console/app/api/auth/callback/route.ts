/**
 * `GET /api/auth/callback` — completes the OAuth flow.
 *
 * PostHog has just redirected the browser here with `?code=...&state=...`.
 * We:
 *   1. Pull the flow cookie set by `/api/auth/login`.
 *   2. Validate `state` matches (CSRF).
 *   3. Exchange `code` (+ `code_verifier`) for tokens via the token endpoint.
 *   4. Seal the token bundle into the session cookie.
 *   5. Redirect the browser back to the originally-requested path.
 *
 * Any failure renders a simple error page rather than redirecting, so
 * the operator can see what went wrong without chasing through redirects.
 */

import { NextResponse } from 'next/server'

import { type AllowlistCheckProfile, checkAccessAllowlist } from '@/lib/auth/allowlist'
import { consumeOAuthFlow, setSession } from '@/lib/auth/session'
import { exchangeAuthorizationCode } from '@/lib/auth/tokens'
import { getConfig } from '@/lib/config'

export async function GET(request: Request): Promise<Response> {
    const url = new URL(request.url)
    const code = url.searchParams.get('code')
    const state = url.searchParams.get('state')
    const error = url.searchParams.get('error')

    if (error) {
        return renderError(`Authorization denied: ${error}`)
    }
    if (!code || !state) {
        return renderError('Missing code or state on callback.')
    }

    const flow = await consumeOAuthFlow()
    if (!flow) {
        return renderError(
            'Login flow expired or no flow cookie found. Try logging in again — most often this is a clock drift or a stale tab.'
        )
    }
    if (flow.state !== state) {
        return renderError('State mismatch — possible CSRF. Try logging in again.')
    }

    try {
        const session = await exchangeAuthorizationCode({ code, codeVerifier: flow.codeVerifier })
        // Resolve the user's current org + team so we can both
        //   (a) gate access against the configured allowlist, and
        //   (b) stamp `teamId` onto the session for the next
        //       `/api/projects/<id>/...` call.
        // Best-effort for `teamId` — login still succeeds if this fails;
        // the agents list surfaces a clean "missing teamId" error
        // downstream. Allowlist enforcement is NOT best-effort: if the
        // allowlist is configured and we can't read the profile, we
        // deny by default. That's the correct fail-closed behaviour for
        // an access control feature.
        const profile = await fetchProfile(session.accessToken)
        const config = getConfig()
        const gateEnabled = config.allowedTeamIds.length > 0
        if (gateEnabled) {
            if (!profile) {
                return renderError(
                    'Could not verify your PostHog account against this deployment’s allowlist (failed to read your profile). Try logging in again; if the problem persists, contact whoever runs this console.'
                )
            }
            const decision = checkAccessAllowlist(profile, config)
            if (!decision.allowed) {
                return renderError(decision.reason ?? 'Your account is not authorized to use this agent console.')
            }
        }
        const teamId = profile?.team?.id ?? undefined
        await setSession({ ...session, teamId })
    } catch (err) {
        return renderError(`Token exchange failed: ${err instanceof Error ? err.message : String(err)}`)
    }

    return NextResponse.redirect(new URL(flow.returnTo, url.origin).toString(), { status: 302 })
}

async function fetchProfile(accessToken: string): Promise<AllowlistCheckProfile | null> {
    try {
        const res = await fetch(`${getConfig().posthogBaseUrl}/api/users/@me/`, {
            headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
        })
        if (!res.ok) {
            return null
        }
        return (await res.json()) as AllowlistCheckProfile
    } catch {
        return null
    }
}

function renderError(message: string): Response {
    const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Sign-in failed — PostHog Agent Console</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, sans-serif; max-width: 36rem; margin: 4rem auto; padding: 1rem; color: #111; }
      h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
      p { color: #444; line-height: 1.5; }
      a { color: #1c64f2; }
    </style>
  </head>
  <body>
    <h1>Sign-in failed</h1>
    <p>${escapeHtml(message)}</p>
    <p><a href="/api/auth/login">Try again</a></p>
  </body>
</html>`
    return new Response(html, { status: 400, headers: { 'Content-Type': 'text/html; charset=utf-8' } })
}

function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}
