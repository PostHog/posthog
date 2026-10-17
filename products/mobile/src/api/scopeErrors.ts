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

/** The first Views scope a grant lacks, or null for an unknown grant. */
export function missingViewsScope(granted: readonly string[] | null): string | null {
    if (!granted) {
        return null
    }
    return VIEWS_SCOPES.find((scope) => !coversScope(granted, scope)) ?? null
}
