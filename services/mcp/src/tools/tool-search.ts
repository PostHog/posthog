import { RE2JS } from 're2js'

/** The runtime `Tool` and the catalog's `ScopeGatedTool` both satisfy this shape. */
export interface SearchableTool {
    name: string
    title: string
    description: string
    searchKeywords?: readonly string[]
}

const SEARCH_FIELD_WEIGHT = { name: 3, title: 2, keywords: 2, description: 1 } as const
export type SearchField = keyof typeof SEARCH_FIELD_WEIGHT

/** A token counts once, at its highest-weight field, so a name hit does not
 *  also score for a description mention. */
const ORDERED_FIELDS: readonly SearchField[] = ['name', 'title', 'keywords', 'description']

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

const MAX_EXPANSION = 20_000
const MAX_PROGRAM_SIZE = 1000
const COUNTED_REPEAT = /\{\s*(\d+)\s*(?:,\s*(\d*)\s*)?\}/g

/** Compiles an agent's search pattern with RE2 so that a short pattern such as `(.*)+Z` cannot backtrack.
 *  RE2 cost grows with the compiled program, which counted repeats such as `{1000}` multiply, nested or not.
 *  The pattern length times every repeat count bounds that program, so it is checked before compiling and
 *  the real program size after. Throws on invalid syntax too. */
export function compileSearchPattern(pattern: string): RE2JS {
    let expansion = pattern.length
    for (const [, min, max] of pattern.matchAll(COUNTED_REPEAT)) {
        expansion *= Math.max(Number(min), Number(max || 0), 1)
        if (expansion > MAX_EXPANSION) {
            throw new Error('search pattern repeats too much')
        }
    }
    const regex = RE2JS.compile(pattern, RE2JS.CASE_INSENSITIVE)
    if (regex.programSize() > MAX_PROGRAM_SIZE) {
        throw new Error('search pattern is too complex')
    }
    return regex
}

/** The `exec search` predicate for regex patterns, ordered by the field that matched so a name
 *  hit comes before a description mention, the way `searchToolsRanked` already orders words.
 *  Ties keep catalog order. Throws if the pattern is not a valid regex, so callers surface their
 *  own error message. */
export function searchToolsRegex<T extends SearchableTool>(tools: readonly T[], pattern: string): T[] {
    const regex = compileSearchPattern(pattern)
    const matched: { tool: T; rank: number }[] = []
    for (const tool of tools) {
        const rank = ORDERED_FIELDS.findIndex((field) =>
            field === 'keywords'
                ? (tool.searchKeywords ?? []).some((keyword) => regex.test(keyword))
                : regex.test(tool[field])
        )
        if (rank !== -1) {
            matched.push({ tool, rank })
        }
    }
    return matched.sort((a, b) => a.rank - b.rank).map((m) => m.tool)
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
            keywords: (t.searchKeywords ?? []).join(' ').toLowerCase(),
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
