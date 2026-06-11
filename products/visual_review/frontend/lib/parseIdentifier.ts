// Pure helpers for splitting a snapshot identifier into theme + area buckets.
// Used by the snapshots-overview scene for client-side facet derivation. Stays
// in sync with `_derive_area` if/when the backend ever needs to mirror it for
// a server-side facet.

export type Theme = 'light' | 'dark' | null

export function parseTheme(identifier: string): { stem: string; theme: Theme } {
    if (identifier.endsWith('--light')) {
        return { stem: identifier.slice(0, -'--light'.length), theme: 'light' }
    }
    if (identifier.endsWith('--dark')) {
        return { stem: identifier.slice(0, -'--dark'.length), theme: 'dark' }
    }
    return { stem: identifier, theme: null }
}

// Tokens that act as "modifier" prefixes inside identifiers like
// `error-tracking`, `data-management`, `feature-flags`. When the area token
// is one of these, we glue it together with the next token so the facet shows
// "Error tracking" instead of just "Error".
const TWO_WORD_HEADS = new Set([
    'customer',
    'data',
    'error',
    'feature',
    'live',
    'llm',
    'marketing',
    'product',
    'revenue',
    'session',
    'user',
    'visual',
    'web',
])

// Capitalize first letter, leave the rest as-is so multi-word labels read
// naturally ("Feature flags" not "Feature Flags").
function titleCase(s: string): string {
    return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1)
}

export function parseArea(identifier: string): string {
    // Storybook identifiers tend to follow one of three shapes:
    //   - `scenes-app-<area>-<rest...>` — the area is the third token
    //   - `components-<rest...>`        — bucket as "Components"
    //   - `<area>-<rest...>`            — first token IS the area
    // Two-word area names ("error-tracking", "data-management") are detected
    // via a tiny TWO_WORD_HEADS set instead of a curated full table.
    const stem = parseTheme(identifier).stem.split('--')[0].toLowerCase()
    const tokens = stem.split('-')
    let i = 0
    if (tokens[i] === 'scenes' && tokens[i + 1] === 'app') {
        i += 2
    }
    if (tokens[i] === 'components') {
        return 'Components'
    }
    if (!tokens[i]) {
        return 'Other'
    }
    const head = TWO_WORD_HEADS.has(tokens[i]) && tokens[i + 1] ? `${tokens[i]} ${tokens[i + 1]}` : tokens[i]
    return titleCase(head)
}

// Display-friendly run-type label ("playwright · chromium" for Playwright runs
// where we know the browser; otherwise just the run_type itself).
export function runTypeLabel(runType: string, browser: string | null | undefined): string {
    if (runType.toLowerCase() === 'playwright' && browser) {
        return `playwright · ${browser}`
    }
    return runType
}
