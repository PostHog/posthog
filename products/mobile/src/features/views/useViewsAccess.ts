import { create } from 'zustand'

import { coversScope, missingFeatureScope, missingScope, type ScopedFeature } from '@/api/scopeErrors'
import { type AuthMethod, addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionTokens, type SessionTokens } from '@/auth/tokens'
import { useDataMode } from '@/demo/demoMode'

const NONE_REPORTED: Record<ScopedFeature, string | null> = { views: null, errors: null, replay: null }

interface ScopeErrorState {
    /** Per feature, the scope one of its requests was refused for in this session. */
    reported: Record<ScopedFeature, string | null>
    report: (feature: ScopedFeature, scope: string) => void
    clear: () => void
}

// Kept per feature, so an issue read refused for `error_tracking:read` does not lock Views as well.
export const useScopeErrorStore = create<ScopeErrorState>()((set) => ({
    reported: NONE_REPORTED,
    report: (feature, scope) => set((state) => ({ reported: { ...state.reported, [feature]: scope } })),
    clear: () => set({ reported: NONE_REPORTED }),
}))

addSessionEndTask(() => useScopeErrorStore.getState().clear())

/**
 * Records a 403 that names a missing scope, so the feature shows the sign-in state instead of a row error. Returns true
 * when the error was one. A 403 for a dashboard the user cannot view is not.
 */
export function reportScopeError(error: unknown, feature: ScopedFeature = 'views'): boolean {
    const scope = missingScope(error)
    if (scope) {
        useScopeErrorStore.getState().report(feature, scope)
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

/** The session facts that decide a feature's access. */
export interface ViewsAccessInput {
    method: AuthMethod | null
    tokens: Pick<SessionTokens, 'grantedScopes' | 'requestedScopes'> | null
    /** The scope one of the feature's requests was refused for in this session. */
    reported: string | null
}

/**
 * Whether a live session can load a feature. An OAuth session that lacks one of the feature's scopes, or that a request
 * reported as lacking one, needs one new sign-in: a refresh never widens a grant. When the sign-in asked for the scope
 * and the grant still lacks it, the app's OAuth application does not offer it, and a new sign-in would not help. A
 * personal API key needs the scopes added to the key.
 */
export function featureAccessFor({ method, tokens, reported }: ViewsAccessInput, feature: ScopedFeature): ViewsAccess {
    const granted = method === 'oauth' ? (tokens?.grantedScopes ?? null) : null
    const missing = reported ?? missingFeatureScope(granted, feature)
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

/** A feature's access for the current session. Demo mode always has access. */
export function useFeatureAccess(feature: ScopedFeature): ViewsAccess {
    const mode = useDataMode()
    const method = useAuthStore((state) => state.method)
    // Changes on every sign-in, so the granted scopes below are read again.
    useAuthStore((state) => state.status)
    const reported = useScopeErrorStore((state) => state.reported[feature])
    if (mode !== 'live') {
        return OK
    }
    return featureAccessFor({ method, tokens: method === 'oauth' ? getSessionTokens() : null, reported }, feature)
}

/** Views access for the current session. */
export function useViewsAccess(): ViewsAccess {
    return useFeatureAccess('views')
}
