/**
 * Browser-side session context — wraps `/api/auth/me` so any component
 * can read the authenticated user's team id, name, email, etc. without
 * each having to fetch it.
 *
 * Loaded once on app mount. Authenticated requests downstream
 * (`apiClient`) read `teamId` via `useSessionTeamId()` and pass it on
 * the URL — no more hardcoded project id.
 *
 * If the fetch returns `authenticated: false` the middleware should
 * already have bounced the browser; this is a safety net for the
 * rare race where the session expired between page load and now.
 */

'use client'

import { createContext, useContext, useEffect, useState } from 'react'

export interface SessionInfo {
    authenticated: boolean
    teamId: number | null
    /** Whatever else `/oauth/userinfo` returned — `sub`, `email`, `name`, etc. */
    [key: string]: unknown
}

interface SessionStore {
    info: SessionInfo | null
    loading: boolean
    error: Error | null
}

const SessionCtx = createContext<SessionStore | null>(null)

export function SessionProvider({ children }: { children: React.ReactNode }): React.ReactElement {
    const [info, setInfo] = useState<SessionInfo | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<Error | null>(null)

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const res = await fetch('/api/auth/me', { headers: { Accept: 'application/json' } })
                if (!res.ok) {
                    throw new Error(`auth/me ${res.status}`)
                }
                const body = (await res.json()) as SessionInfo
                if (!cancelled) {
                    setInfo(body)
                    setLoading(false)
                }
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err : new Error(String(err)))
                    setLoading(false)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [])

    return <SessionCtx.Provider value={{ info, loading, error }}>{children}</SessionCtx.Provider>
}

export function useSession(): SessionStore {
    const store = useContext(SessionCtx)
    if (!store) {
        return { info: null, loading: false, error: null }
    }
    return store
}

export function useSessionTeamId(): number | null {
    const { info } = useSession()
    return info?.teamId ?? null
}

export interface SessionUser {
    email: string | null
    firstName: string | null
    lastName: string | null
    /** Convenience: 2-char uppercase initials from the name or email. */
    initials: string
    /** Convenience: name when present, falling back to the email's local part. */
    displayName: string
}

export function useSessionUser(): SessionUser | null {
    const { info } = useSession()
    const profile = (info?.profile ?? null) as {
        email?: string | null
        first_name?: string | null
        last_name?: string | null
    } | null
    if (!profile) {
        return null
    }
    const firstName = profile.first_name ?? null
    const lastName = profile.last_name ?? null
    const email = profile.email ?? null
    const displayName = [firstName, lastName].filter(Boolean).join(' ').trim() || email?.split('@')[0] || 'Account'
    const initials = computeInitials(firstName, lastName, email)
    return { email, firstName, lastName, initials, displayName }
}

function computeInitials(first: string | null, last: string | null, email: string | null): string {
    const fromName = [first, last]
        .filter((s): s is string => !!s && s.length > 0)
        .map((s) => s[0]!.toUpperCase())
        .join('')
    if (fromName.length > 0) {
        return fromName.slice(0, 2)
    }
    if (email) {
        return email.slice(0, 2).toUpperCase()
    }
    return '??'
}

export function usePosthogBaseUrl(): string | null {
    const { info } = useSession()
    const url = (info as { posthogBaseUrl?: string } | null)?.posthogBaseUrl ?? null
    return url
}

/**
 * `<SessionGate>` — blocks rendering until `/api/auth/me` resolves
 * (or errors). Mount it once inside the AppShell so child pages can
 * assume the session info is loaded and don't each need their own
 * "Resolving project…" placeholder.
 */
export function SessionGate({ children }: { children: React.ReactNode }): React.ReactElement {
    const { loading, error, info } = useSession()
    if (loading) {
        return (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading session…
            </div>
        )
    }
    if (error) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-destructive-foreground">
                <p>Couldn't reach the session endpoint: {error.message}</p>
                <ServerAnchor href="/api/auth/login">Try logging in again</ServerAnchor>
            </div>
        )
    }
    if (!info || !info.authenticated) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-muted-foreground">
                <p>Not signed in.</p>
                <ServerAnchor href="/api/auth/login">Sign in</ServerAnchor>
            </div>
        )
    }
    if (info.teamId == null) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-sm text-destructive-foreground">
                <p>Your account has no current project. Open PostHog and pick a project, then reload.</p>
                <ServerAnchor href="/api/auth/logout">Sign out</ServerAnchor>
            </div>
        )
    }
    return <>{children}</>
}

/**
 * Anchor for `/api/auth/*` routes — these must trigger a real HTTP
 * request (server-side cookie reads, redirects), not Next.js's
 * client-side navigation. Plain `<a>` is correct here; the linter
 * rule that nudges toward `<Link>` doesn't know that.
 */
function ServerAnchor({ href, children }: { href: string; children: React.ReactNode }): React.ReactElement {
    return (
        // eslint-disable-next-line react/forbid-elements
        <a href={href} className="underline">
            {children}
        </a>
    )
}
