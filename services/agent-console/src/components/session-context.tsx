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
