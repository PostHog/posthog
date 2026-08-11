import type { ConfigVersionApi } from '../generated/api.schemas'

const VERSION_SUFFIX_RE = /v(\d+)/g

// Mirrors the server's suggestion (_next_version in api/ai_enrichment.py): the highest `v<digits>`
// occurring anywhere in any existing version string for this label, plus one - so a legacy name
// like "ai-pilled-clay-v1" still contributes its 1, not just an exact "v1". Falls back to one past
// the version count only when nothing on record has a v<n> pattern at all. The server has the
// last word - it re-derives this itself from a row lock and accepts a caller-supplied version
// regardless - so a client/server mismatch here (e.g. a version saved outside this UI) only
// changes the prefilled suggestion, never what's allowed.
export function suggestNextVersion(versions: ConfigVersionApi[]): string {
    let highest: number | null = null
    for (const version of versions) {
        for (const match of version.version.matchAll(VERSION_SUFFIX_RE)) {
            highest = Math.max(highest ?? 0, parseInt(match[1], 10))
        }
    }
    return highest !== null ? `v${highest + 1}` : `v${versions.length + 1}`
}
