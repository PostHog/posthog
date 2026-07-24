// Trailing `v<int>` bumps in place (e.g. `ai-pilled-clay-v1` -> `ai-pilled-clay-v2`); anything
// else gets `-v2` appended so the suggestion is always a fresh, non-colliding version string.
const TRAILING_V_INT_RE = /^(.*v)(\d+)$/

export function suggestNextVersion(version: string): string {
    const trimmed = version.trim()
    if (!trimmed) {
        return 'v1'
    }
    const match = trimmed.match(TRAILING_V_INT_RE)
    if (match) {
        const [, prefix, digits] = match
        return `${prefix}${Number(digits) + 1}`
    }
    return `${trimmed}-v2`
}
