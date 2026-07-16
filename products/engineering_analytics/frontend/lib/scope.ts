import { combineUrl } from 'kea-router'

/** Carry the shared window + branch scope (and active source/repo) onto an internal nav URL, so drilling
 *  in, switching workflows, or stepping back never silently resets it. The scope lives in the URL — every
 *  cross-page link threads it the same way the tab links do (`?date_from` / `?date_to` / `?q` / `?source`
 *  / `?repo`). The pull-request lens (`?run_scope`) is intentionally not carried: only workflow health
 *  honors it, so it stays on the Workflows tab rather than following a drill-down that can't apply it. */
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
        // Carry the repo scope of a multi-repo source (set by the picker) the same way as `?q` — from
        // the current URL — so every withScope-based link preserves it with no caller change.
        ...(searchParams.repo ? { repo: searchParams.repo } : {}),
    }).url
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
