import { combineUrl, router } from 'kea-router'

/** Carries the shared window, run scope, and source onto an internal URL, so a drill-in or a step back
 *  never resets them. The repository is in the path, never a param. */
export function withScope(
    url: string,
    searchParams: Record<string, string | undefined>,
    sourceId: string | null | undefined
): string {
    return combineUrl(url, {
        ...(searchParams.date_from ? { date_from: searchParams.date_from } : {}),
        ...(searchParams.date_to ? { date_to: searchParams.date_to } : {}),
        ...(searchParams.run_scope ? { run_scope: searchParams.run_scope } : {}),
        ...(sourceId ? { source: sourceId } : {}),
    }).url
}

/** Reads the live URL, for module-level link builders that have no searchParams in scope. */
export function withCurrentScope(url: string, sourceId: string | null | undefined): string {
    return withScope(url, router.values.searchParams, sourceId)
}

/** `::` never appears in a UUID or an 'owner/name', so the split is safe. */
export function scopeToValue(sourceId: string, repo: string): string {
    return `${sourceId}::${repo}`
}

export function scopeFromValue(value: string): { sourceId: string; repo: string | null } {
    const sep = value.indexOf('::')
    if (sep === -1) {
        return { sourceId: value, repo: null }
    }
    // A blank repo (a source with no configured repo) decodes to null, which selects the backend's default repo.
    return { sourceId: value.slice(0, sep), repo: value.slice(sep + 2) || null }
}
