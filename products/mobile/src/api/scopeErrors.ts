import { ApiError } from './client'

// `APIScopePermission` in `posthog/permissions.py` answers a token without the scope with 403 and this detail. A 403
// for anything else, such as a dashboard the user cannot view, has another detail and must not ask for a new sign-in.
const MISSING_SCOPE = /missing required scope '([^']+)'/

/** The scope a 403 names as missing, such as `dashboard:read`, or null for any other error. */
export function missingScope(error: unknown): string | null {
    if (!(error instanceof ApiError) || error.status !== 403) {
        return null
    }
    return MISSING_SCOPE.exec(error.detail ?? '')?.[1] ?? null
}

/** The scopes Views needs on top of the app's others. `file_system_shortcut:write` also grants the read. */
export const VIEWS_SCOPES = ['dashboard:read', 'insight:read', 'file_system_shortcut:write'] as const

/** True when the scopes include `scope`. A `:write` scope covers the matching `:read`. */
export function coversScope(scopes: readonly string[], scope: string): boolean {
    const [object, level] = scope.split(':')
    return scopes.includes(scope) || (level === 'read' && scopes.includes(`${object}:write`))
}

/** The scopes the issues list and issue screen need. The write covers status and assignee changes. */
export const ERRORS_SCOPES = ['error_tracking:read', 'error_tracking:write'] as const

/** The scopes the sessions list and session screen need. `replay_scanner` covers the AI summary. */
export const REPLAY_SCOPES = ['session_recording:read', 'replay_scanner:read', 'replay_scanner:write'] as const

export type ScopedFeature = 'views' | 'errors' | 'replay'

export const FEATURE_SCOPES: Record<ScopedFeature, readonly string[]> = {
    views: VIEWS_SCOPES,
    errors: ERRORS_SCOPES,
    replay: REPLAY_SCOPES,
}

/** The first scope of `feature` a grant lacks, or null for an unknown grant. */
export function missingFeatureScope(granted: readonly string[] | null, feature: ScopedFeature): string | null {
    if (!granted) {
        return null
    }
    return FEATURE_SCOPES[feature].find((scope) => !coversScope(granted, scope)) ?? null
}

/** The first Views scope a grant lacks, or null for an unknown grant. */
export function missingViewsScope(granted: readonly string[] | null): string | null {
    return missingFeatureScope(granted, 'views')
}
