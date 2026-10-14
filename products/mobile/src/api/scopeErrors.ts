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
