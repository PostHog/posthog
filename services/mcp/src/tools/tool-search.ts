/** The runtime `Tool` and the catalog's `ScopeGatedTool` both satisfy this shape. */
export interface SearchableTool {
    name: string
    title: string
    description: string
}

const SEARCH_FIELD_WEIGHT = { name: 3, title: 2, description: 1 } as const
export type SearchField = keyof typeof SEARCH_FIELD_WEIGHT

/** A token counts once, at its highest-weight field, so a name hit does not
 *  also score for a description mention. */
const ORDERED_FIELDS: readonly SearchField[] = ['name', 'title', 'description']

export interface RankedToolMatch {
    name: string
    tokensMatched: number
    score: number
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

/** The original `exec search` predicate, kept verbatim. Throws if the pattern
 *  is not a valid regex, so callers surface their own error message. */
export function searchToolsRegex<T extends SearchableTool>(tools: readonly T[], pattern: string): T[] {
    const regex = new RegExp(pattern, 'i')
    return tools.filter((t) => regex.test(t.name) || regex.test(t.title) || regex.test(t.description))
}

/** Multi-word queries like "create dashboard insight" match nothing as a single
 *  regex, so rank tools by the query tokens they contain instead. */
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
    // Name is the last key so equal matches keep a stable order.
    scored.sort((a, b) => b.score - a.score || b.tokensMatched - a.tokensMatched || a.name.localeCompare(b.name))
    return scored
}
