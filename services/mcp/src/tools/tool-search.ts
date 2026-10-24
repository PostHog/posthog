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

/** Words that carry no intent. Substring matching let "the" or "a" score on
 *  nearly every description; they are dropped before ranking. */
const STOPWORDS = new Set([
    'a',
    'an',
    'the',
    'to',
    'of',
    'for',
    'on',
    'in',
    'by',
    'with',
    'and',
    'or',
    'my',
    'me',
    'i',
    'is',
    'are',
    'how',
    'what',
    'which',
    'this',
    'that',
    'it',
    'from',
    'into',
    'about',
    'please',
])

/** How agents and users word an intent versus how tool names and titles word it.
 *  Each query word also matches its alternatives; it still counts as one token. */
const SYNONYMS: Record<string, readonly string[]> = {
    show: ['get', 'retrieve', 'list', 'view'],
    view: ['get', 'retrieve', 'show'],
    see: ['get', 'retrieve', 'list'],
    display: ['get', 'retrieve', 'show'],
    fetch: ['get', 'retrieve'],
    read: ['get', 'retrieve'],
    details: ['get', 'retrieve'],
    find: ['search', 'get', 'list', 'lookup'],
    lookup: ['get', 'search'],
    browse: ['list'],
    list: ['all'],
    add: ['create'],
    new: ['create'],
    make: ['create'],
    remove: ['delete', 'destroy'],
    delete: ['destroy'],
    drop: ['delete', 'destroy'],
    edit: ['update', 'patch'],
    change: ['update', 'patch'],
    modify: ['update', 'patch'],
    rename: ['update'],
    execute: ['run'],
    run: ['execute'],
    start: ['launch', 'enable'],
    launch: ['start'],
    stop: ['end', 'disable'],
    end: ['stop'],
    user: ['person'],
    users: ['person'],
    people: ['person'],
    replay: ['recording'],
    replays: ['recording'],
}

const SUFFIXES = ['ments', 'ment', 'ings', 'ing', 'ions', 'ion', 'ers', 'er', 'ed', 'es', 's', 'e'] as const

/** Light suffix folding: `flags`/`flag`, `queries`/`query`, `deployment`/`deploy` and
 *  `annotation`/`annotate` meet, while `view`/`review` and `person`/`personal` stay
 *  apart because only suffixes are folded, never prefixes or arbitrary endings. */
function stem(word: string): string {
    if (word.length > 4 && word.endsWith('ies')) {
        return `${word.slice(0, -3)}y`
    }
    for (const suffix of SUFFIXES) {
        if (word.endsWith(suffix) && word.length - suffix.length >= 3 && !word.endsWith('ss')) {
            return word.slice(0, -suffix.length)
        }
    }
    return word
}

/** A synonym is a weaker signal than the word the agent actually typed. */
const SYNONYM_WEIGHT = 0.6

function words(text: string): Set<string> {
    return new Set(
        text
            .toLowerCase()
            .split(/[^a-z0-9]+/)
            .filter(Boolean)
            .map(stem)
    )
}

/** One query token: the word as typed (stemmed) and its stemmed synonyms. */
interface QueryToken {
    exact: string
    synonyms: string[]
}

/** "turn off" and "turn on" are one intent each, not two words. */
function queryTokens(query: string): QueryToken[] {
    const raw = query
        .toLowerCase()
        .replace(/\bturn\s+off\b/g, 'disable')
        .replace(/\bturn\s+on\b/g, 'enable')
    const tokens = [...new Set(raw.split(/[^a-z0-9]+/).filter((w) => w && !STOPWORDS.has(w)))]
    return tokens.map((t) => {
        const exact = stem(t)
        return { exact, synonyms: [...new Set((SYNONYMS[t] ?? []).map(stem))].filter((s) => s !== exact) }
    })
}

interface IndexedTool {
    name: string
    fieldWords: Record<SearchField, Set<string>>
    nameLength: number
}

/** Tokenized tools, keyed by name and checked against the text they were built from,
 *  so rebuilt tool objects with unchanged definitions reuse their index. Bounded, since
 *  connected third-party servers can contribute tools too. */
const INDEX = new Map<string, { title: string; description: string; indexed: IndexedTool }>()
const MAX_INDEXED_TOOLS = 5000

function indexTool(t: SearchableTool): IndexedTool {
    const cached = INDEX.get(t.name)
    if (cached && cached.title === t.title && cached.description === t.description) {
        return cached.indexed
    }
    const indexed: IndexedTool = {
        name: t.name,
        fieldWords: { name: words(t.name), title: words(t.title), description: words(t.description) },
        nameLength: t.name.split('-').length,
    }
    if (INDEX.size >= MAX_INDEXED_TOOLS) {
        INDEX.clear()
    }
    INDEX.set(t.name, { title: t.title, description: t.description, indexed })
    return indexed
}

/** Multi-word queries like "create dashboard insight" match nothing as a single
 *  regex, so rank tools by the query tokens they contain instead. Tokens match
 *  whole words (after plural folding and synonyms), and a token that appears in
 *  few tools counts for more than one that appears in most of them. */
export function searchToolsRanked<T extends SearchableTool>(tools: readonly T[], query: string): RankedToolMatch[] {
    const tokens = queryTokens(query)
    if (tokens.length === 0) {
        return []
    }
    const indexed = tools.map(indexTool)
    const inAnyField = (tool: IndexedTool, token: QueryToken): boolean =>
        ORDERED_FIELDS.some((f) => [token.exact, ...token.synonyms].some((w) => tool.fieldWords[f].has(w)))
    const idf = tokens.map((token) => {
        const df = indexed.filter((tool) => inAnyField(tool, token)).length
        return Math.log(1 + tools.length / (1 + df))
    })

    const scored: { match: RankedToolMatch; nameLength: number }[] = []
    for (const tool of indexed) {
        let tokensMatched = 0
        let score = 0
        const fields = new Set<SearchField>()
        tokens.forEach((token, i) => {
            const exactField = ORDERED_FIELDS.find((f) => tool.fieldWords[f].has(token.exact))
            const synonymField = ORDERED_FIELDS.find((f) => token.synonyms.some((s) => tool.fieldWords[f].has(s)))
            const exactScore = exactField ? SEARCH_FIELD_WEIGHT[exactField] : 0
            const synonymScore = synonymField ? SEARCH_FIELD_WEIGHT[synonymField] * SYNONYM_WEIGHT : 0
            if (exactField || synonymField) {
                tokensMatched += 1
                score += Math.max(exactScore, synonymScore) * idf[i]
                fields.add(exactScore >= synonymScore && exactField ? exactField : (synonymField as SearchField))
            }
        })
        if (tokensMatched > 0) {
            scored.push({
                match: { name: tool.name, tokensMatched, score: Math.round(score * 1000) / 1000, fields: [...fields] },
                nameLength: tool.nameLength,
            })
        }
    }
    // Among equal scores the tool with the shorter name is the general one
    // ("experiment-get" before "experiment-get-by-flag-key"); name keeps the order stable.
    scored.sort(
        (a, b) =>
            b.match.score - a.match.score ||
            b.match.tokensMatched - a.match.tokensMatched ||
            a.nameLength - b.nameLength ||
            a.match.name.localeCompare(b.match.name)
    )
    return scored.map((s) => s.match)
}
