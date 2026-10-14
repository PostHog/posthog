import { create } from 'zustand'

import { missingScope, missingViewsScope } from '@/api/scopeErrors'
import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionTokens } from '@/auth/tokens'
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

export type ViewsAccessState = 'ok' | 'reauth' | 'personal-key-missing-scopes'

export interface ViewsAccess {
    state: ViewsAccessState
    /** For `mobile_views_reauth_shown`. */
    missingScope: string | null
}

const OK: ViewsAccess = { state: 'ok', missingScope: null }

/**
 * Whether Views can load. An OAuth session that lacks a Views scope, or that a Views request reported as lacking one,
 * needs one new sign-in: a refresh never widens a grant. A personal API key needs the scopes added to the key.
 * Demo mode always has access.
 */
export function useViewsAccess(): ViewsAccess {
    const mode = useDataMode()
    const method = useAuthStore((state) => state.method)
    // Changes on every sign-in, so the granted scopes below are read again.
    useAuthStore((state) => state.status)
    const reported = useViewsScopeStore((state) => state.missingScope)
    if (mode !== 'live') {
        return OK
    }
    const granted = method === 'oauth' ? (getSessionTokens()?.grantedScopes ?? null) : null
    const missing = reported ?? missingViewsScope(granted)
    if (!missing) {
        return OK
    }
    return { state: method === 'personal_api_key' ? 'personal-key-missing-scopes' : 'reauth', missingScope: missing }
}
