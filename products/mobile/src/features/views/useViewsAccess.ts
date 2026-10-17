import { create } from 'zustand'

import { coversScope, missingScope, missingViewsScope } from '@/api/scopeErrors'
import { type AuthMethod, addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionTokens, type SessionTokens } from '@/auth/tokens'
import { useDataMode } from '@/demo/demoMode'

interface ViewsScopeState {
    /** The scope a Views request was refused for in this session. */
    missingScope: string | null
    report: (scope: string) => void
    clear: () => void
}

export const useViewsScopeStore = create<ViewsScopeState>()((set) => ({
    missingScope: null,
    report: (scope) => set({ missingScope: scope }),
    clear: () => set({ missingScope: null }),
}))

addSessionEndTask(() => useViewsScopeStore.getState().clear())

/**
 * Records a 403 that names a missing scope, so Views shows the sign-in state instead of a row error. Returns true when
 * the error was one. A 403 for a dashboard the user cannot view is not.
 */
export function reportScopeError(error: unknown): boolean {
    const scope = missingScope(error)
    if (scope) {
        useViewsScopeStore.getState().report(scope)
    }
    return scope !== null
}

/**
 * `reauth`: one new sign-in adds the scope. `unavailable`: the last sign-in asked for the scope and the server left it
 * out, because the app's OAuth application does not offer it yet, so a new sign-in would get the same grant.
 */
export type ViewsAccessState = 'ok' | 'reauth' | 'unavailable' | 'personal-key-missing-scopes'

export interface ViewsAccess {
    state: ViewsAccessState
    /** For `mobile_views_reauth_shown`. */
    missingScope: string | null
}

const OK: ViewsAccess = { state: 'ok', missingScope: null }

/** The session facts that decide Views access. */
export interface ViewsAccessInput {
    method: AuthMethod | null
    tokens: Pick<SessionTokens, 'grantedScopes' | 'requestedScopes'> | null
    /** The scope a Views request was refused for in this session. */
    reported: string | null
}

/**
 * Whether a live session can load Views. An OAuth session that lacks a Views scope, or that a Views request reported
 * as lacking one, needs one new sign-in: a refresh never widens a grant. When the sign-in asked for the scope and the
 * grant still lacks it, the app's OAuth application does not offer it, and a new sign-in would not help. A personal
 * API key needs the scopes added to the key.
 */
export function viewsAccessFor({ method, tokens, reported }: ViewsAccessInput): ViewsAccess {
    const granted = method === 'oauth' ? (tokens?.grantedScopes ?? null) : null
    const missing = reported ?? missingViewsScope(granted)
    if (!missing) {
        return OK
    }
    if (method === 'personal_api_key') {
        return { state: 'personal-key-missing-scopes', missingScope: missing }
    }
    const clamped =
        granted !== null && !coversScope(granted, missing) && coversScope(tokens?.requestedScopes ?? [], missing)
    return { state: clamped ? 'unavailable' : 'reauth', missingScope: missing }
}

/** Views access for the current session. Demo mode always has access. */
export function useViewsAccess(): ViewsAccess {
    const mode = useDataMode()
    const method = useAuthStore((state) => state.method)
    // Changes on every sign-in, so the granted scopes below are read again.
    useAuthStore((state) => state.status)
    const reported = useViewsScopeStore((state) => state.missingScope)
    if (mode !== 'live') {
        return OK
    }
    return viewsAccessFor({ method, tokens: method === 'oauth' ? getSessionTokens() : null, reported })
}
