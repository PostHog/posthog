/**
 * Tool-search logic for `exec search` (src/tools/exec.ts).
 *
 * Two strategies live here:
 *
 *   - searchToolsRegex  — the original `exec search` predicate: one
 *     case-insensitive RegExp tested against name/title/description.
 *   - searchToolsRanked — a forgiving, field-weighted token ranking so
 *     multi-word natural-language queries ("create dashboard insight") surface
 *     the relevant tools instead of matching nothing.
 *
 * Callers route between them via `isRegexPattern`.
 */

/** Minimal structural shape both searches operate on. The runtime `Tool` and
 *  the catalog's `ScopeGatedTool` both satisfy it, so a single signature serves
 *  every caller. */
export interface SearchableTool {
    name: string
    title: string
    description: string
}

/** A match in a tool's name outweighs the same token in its title, which in
 *  turn outweighs a hit buried in the description. */
const SEARCH_FIELD_WEIGHT = { name: 3, title: 2, description: 1 } as const
export type SearchField = keyof typeof SEARCH_FIELD_WEIGHT

/** Fields in descending weight — a token is counted once, at its highest-weight
 *  field, so a name hit doesn't also score for a description mention. */
const ORDERED_FIELDS: readonly SearchField[] = ['name', 'title', 'description']

export interface RankedToolMatch {
    name: string
    /** Distinct query tokens found in any field — the relevance signal a tie
     *  breaks on after the weighted score. */
    tokensMatched: number
    /** Field-weighted score; the primary ranking key. */
    score: number
    /** Which fields contributed, for debug/inspection output. */
    fields: SearchField[]
}

/** Regex metacharacters that mark a pattern as a deliberate regex rather than
 *  plain words. A pattern containing any of these routes to `searchToolsRegex`
 *  (preserving power-user patterns like `query-` or `feature-flag`); everything
 *  else routes to `searchToolsRanked`. */
const REGEX_METACHARACTER = /[-|()[\]\\.*+^$?]/

export function isRegexPattern(pattern: string): boolean {
    return REGEX_METACHARACTER.test(pattern)
}

/** The original `exec search` predicate, verbatim: a single case-insensitive
 *  RegExp tested against each tool's name, title, and description. Throws if the
 *  pattern is not a valid regex — callers surface their own error message. */
export function searchToolsRegex<T extends SearchableTool>(tools: readonly T[], pattern: string): T[] {
    const regex = new RegExp(pattern, 'i')
    return tools.filter((t) => regex.test(t.name) || regex.test(t.title) || regex.test(t.description))
}

/** Forgiving, field-weighted token search. Splits the query on whitespace and
 *  ranks each tool by a weighted score over the distinct query tokens it
 *  contains, so a multi-word intent like "create dashboard insight" surfaces
 *  dashboard-create / insight-create instead of returning nothing. Results are
 *  sorted by score, then by distinct token coverage, then by name. */
export function searchToolsRanked<T extends SearchableTool>(tools: readonly T[], query: string): RankedToolMatch[] {
    const tokens = [...new Set(query.toLowerCase().split(/\s+/).filter(Boolean))]
    if (tokens.length === 0) {
        return []
    }
    const scored: RankedToolMatch[] = []
    for (const t of tools) {
        const haystack: Record<SearchField, string> = {
            name: t.name.toLowerCase(),
            title: t.title.toLowerCase(),
            description: t.description.toLowerCase(),
        }
        let tokensMatched = 0
        let score = 0
        const fields = new Set<SearchField>()
        for (const token of tokens) {
            // Count each token once, at its highest-weight field, so a token in
            // the name outweighs the same token buried in a description.
            const field = ORDERED_FIELDS.find((f) => haystack[f].includes(token))
            if (field) {
                tokensMatched += 1
                score += SEARCH_FIELD_WEIGHT[field]
                fields.add(field)
            }
        }
        if (tokensMatched > 0) {
            scored.push({ name: t.name, tokensMatched, score, fields: [...fields] })
        }
    }
    // Field-weighted score first: a token in the tool name beats the same token
    // buried in a description, so dashboard-create outranks a tool that merely
    // mentions "create"/"dashboard"/"insight" in prose. Token coverage breaks
    // ties, then name for a stable order.
    scored.sort((a, b) => b.score - a.score || b.tokensMatched - a.tokensMatched || a.name.localeCompare(b.name))
    return scored
}
