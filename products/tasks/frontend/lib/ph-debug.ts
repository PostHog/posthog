import { router } from 'kea-router'

/**
 * Read the `?ph_debug=true` opt-in from the current URL. When set, the backend
 * relaxes the per-creator visibility filter on read-only task/run lookups for
 * PostHog-internal debugging (US-prod team only).
 *
 * Use `phDebugQueryParams()` with API helpers that take a params object
 * (`api.tasks.get`, `api.tasks.runs.get`, …) — they pipe it through
 * `withQueryString`. Use `phDebugQuerySuffix()` when building a request URL by
 * hand (e.g. the `/logs/` proxy endpoint that `loadLogs` consumes).
 */
function isPhDebugSet(): boolean {
    const value = router.values.searchParams?.ph_debug
    return value === 'true' || value === true
}

export function phDebugQueryParams(): { ph_debug?: 'true' } {
    return isPhDebugSet() ? { ph_debug: 'true' } : {}
}

export function phDebugQuerySuffix(): '' | '?ph_debug=true' {
    return isPhDebugSet() ? '?ph_debug=true' : ''
}
