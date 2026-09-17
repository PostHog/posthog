import { combineUrl, router } from 'kea-router'

/** Carry the shared window + run scope (and active source/repo) onto an internal nav URL, so drilling in,
 *  switching workflows, or stepping back never silently resets it. The scope lives in the URL, and every
 *  cross-page link threads it the same way the tab links do (`?date_from` / `?date_to` / `?run_scope` /
 *  `?source` / `?repo`). Every workflow surface reads `run_scope`, so a drill-down keeps the same group
 *  of runs instead of widening back to all of them. */
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
        // Carry the repo scope of a multi-repo source (set by the picker) from the current URL the same
        // way as `?run_scope`, so every withScope-based link preserves it with no caller change.
        ...(searchParams.repo ? { repo: searchParams.repo } : {}),
    }).url
}

/** Like withScope, but reads the live URL for module-level link builders that don't have searchParams in
 *  scope, so a source-only link still carries the current window / run scope / repo. */
export function withCurrentScope(url: string, sourceId: string | null | undefined): string {
    return withScope(url, router.values.searchParams, sourceId)
}

/** Encode a (source, repo) selection as one string for the repo picker's LemonSelect value, since a
 *  source can offer several repos. `::` never appears in a UUID or an 'owner/name', so the split is safe. */
export function scopeToValue(sourceId: string, repo: string): string {
    return `${sourceId}::${repo}`
}

export function scopeFromValue(value: string): { sourceId: string; repo: string | null } {
    const sep = value.indexOf('::')
    if (sep === -1) {
        return { sourceId: value, repo: null }
    }
    // A blank repo (a source with no configured repo) decodes to null → backend default repo.
    return { sourceId: value.slice(0, sep), repo: value.slice(sep + 2) || null }
}
