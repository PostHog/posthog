import { combineUrl } from 'kea-router'

/** Carry the shared window + branch scope (and active source) onto an internal nav URL, so drilling in,
 *  switching workflows, or stepping back never silently resets it. The scope lives in the URL — every
 *  cross-page link threads it the same way the tab links do (`?date_from` / `?date_to` / `?q` / `?source`).
 *  The pull-request lens (`?run_scope`) is intentionally not carried: only workflow health honors it, so it
 *  stays on the Workflows tab rather than following a drill-down that can't apply it. */
export function withScope(
    url: string,
    searchParams: Record<string, string | undefined>,
    sourceId: string | null | undefined
): string {
    return combineUrl(url, {
        ...(searchParams.date_from ? { date_from: searchParams.date_from } : {}),
        ...(searchParams.date_to ? { date_to: searchParams.date_to } : {}),
        ...(searchParams.q ? { q: searchParams.q } : {}),
        ...(sourceId ? { source: sourceId } : {}),
    }).url
}
