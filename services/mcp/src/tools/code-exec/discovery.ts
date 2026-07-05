/**
 * SDK surface discovery for the `types` / `types show` exec verbs. Search and
 * expansion run over the generated discovery index (a codegen-time artifact),
 * never over runtime type-walking. Results are scope-annotated per session so
 * agents know before writing a script which methods their token can call.
 */

import { hasScopes } from '@/lib/api'

/** Mirrors one `methods[]` record of `generated/code-exec/discovery-index.json`. */
export interface DiscoveryMethod {
    /** `<domain>.<method>` as exposed on the SDK client. */
    id: string
    /** Originating MCP tool name; `null` for SDK-only surface. */
    toolName: string | null
    signature: string
    title: string
    description: string
    category: string
    scopes: string[]
    referencedTypes: string[]
}

/** Mirrors one `types[]` record of the discovery index. */
export interface DiscoveryType {
    name: string
    declaration: string
    /** Direct references only — the BFS closure is computed at query time. */
    referencedTypes: string[]
    /** Precomputed `ceil(declaration.length / 4)`. */
    tokens: number
}

export interface DiscoveryIndex {
    version: number
    methods: DiscoveryMethod[]
    types: DiscoveryType[]
}

/** Mirrors the exec `search` verb's guard against pathological regexes. */
const MAX_TYPES_PATTERN_LENGTH = 200

/** Cap on one-line results per search, with a refine hint when exceeded. */
const MAX_SEARCH_RESULTS = 40

/**
 * Token budget for a `types show` response. Sized so one expansion usually
 * answers (declaration + its reference closure) without flooding the model's
 * context — roughly half the exec layer's serialized-response cap.
 */
export const TYPES_SHOW_TOKEN_BUDGET = 6000

const SHOW_HINT = 'Run "types show <domain.method | TypeName | domain>" to expand declarations.'

export interface Discovery {
    search(query: string, sessionScopes: string[]): string
    show(target: string, sessionScopes: string[]): string
}

/** Annotate a signature with the session's scope standing, e.g. `[requires feature_flag:write ✓]`. */
function scopeAnnotation(requiredScopes: string[], sessionScopes: string[]): string {
    if (requiredScopes.length === 0) {
        return ''
    }
    const satisfied = hasScopes(sessionScopes, requiredScopes)
    return ` [requires ${requiredScopes.join(', ')} ${satisfied ? '✓' : '— missing on this token'}]`
}

/** Case-insensitive matcher: a valid pattern is a regex, an invalid one falls back to substring. */
function buildMatcher(pattern: string): (text: string) => boolean {
    try {
        const regex = new RegExp(pattern, 'i')
        return (text) => regex.test(text)
    } catch {
        const needle = pattern.toLowerCase()
        return (text) => text.toLowerCase().includes(needle)
    }
}

function methodLine(method: DiscoveryMethod, sessionScopes: string[]): string {
    const title = method.title ? ` — ${method.title}` : ''
    return `${method.signature}${title}${scopeAnnotation(method.scopes, sessionScopes)}`
}

export function createDiscovery(index: DiscoveryIndex): Discovery {
    const typesByName = new Map<string, DiscoveryType>()
    for (const type of index.types) {
        typesByName.set(type.name.toLowerCase(), type)
    }
    const methodsById = new Map<string, DiscoveryMethod>()
    for (const method of index.methods) {
        methodsById.set(method.id.toLowerCase(), method)
    }

    /**
     * Greedy BFS over the type-reference graph: direct references first, then
     * transitive, each included only while its precomputed token count fits the
     * remaining budget. A type that doesn't fit is skipped (not a hard stop) so
     * smaller types later in the queue can still land; skipped names come back
     * as truncation hints naming the follow-up call.
     */
    const fillTypes = (seedRefs: string[], budget: number): { included: DiscoveryType[]; truncated: string[] } => {
        const included: DiscoveryType[] = []
        const truncated: string[] = []
        const visited = new Set<string>()
        const queue = [...seedRefs]
        let remaining = budget
        while (queue.length > 0) {
            const name = queue.shift()!
            const key = name.toLowerCase()
            if (visited.has(key)) {
                continue
            }
            visited.add(key)
            const type = typesByName.get(key)
            if (!type) {
                continue
            }
            if (type.tokens > remaining) {
                truncated.push(type.name)
                continue
            }
            included.push(type)
            remaining -= type.tokens
            queue.push(...type.referencedTypes)
        }
        return { included, truncated }
    }

    const renderTypeSection = (included: DiscoveryType[], truncated: string[]): string[] => {
        const parts = included.map((type) => type.declaration)
        if (truncated.length > 0) {
            parts.push(
                truncated
                    .map((name) => `Omitted (token budget): ${name} — run "types show ${name}" for the declaration`)
                    .join('\n')
            )
        }
        return parts
    }

    return {
        search(query, sessionScopes) {
            if (query.length > MAX_TYPES_PATTERN_LENGTH) {
                throw new Error(
                    `Search pattern too long (${query.length} chars, max ${MAX_TYPES_PATTERN_LENGTH}). Use a shorter, more targeted pattern.`
                )
            }
            // The compiled regex carries no `g`/`y` flag, so it is stateless and
            // safe to reuse across candidates.
            const matcher = buildMatcher(query)
            const matches = index.methods.filter(
                (method) =>
                    matcher(method.id) ||
                    matcher(method.signature) ||
                    matcher(method.title) ||
                    matcher(method.description) ||
                    method.referencedTypes.some(matcher)
            )
            if (matches.length === 0) {
                return `No SDK methods matched "${query}". Try a broader pattern, or "types show <domain>" for a whole resource.`
            }

            const shown = matches.slice(0, MAX_SEARCH_RESULTS)
            const byCategory = new Map<string, DiscoveryMethod[]>()
            for (const method of shown) {
                const group = byCategory.get(method.category)
                if (group) {
                    group.push(method)
                } else {
                    byCategory.set(method.category, [method])
                }
            }

            const lines: string[] = []
            for (const [category, methods] of byCategory) {
                lines.push(`${category}:`)
                for (const method of methods) {
                    lines.push(`  ${methodLine(method, sessionScopes)}`)
                }
            }
            if (matches.length > shown.length) {
                lines.push(
                    '',
                    `Showing ${shown.length} of ${matches.length} matches — refine the query to see the rest.`
                )
            }
            lines.push('', SHOW_HINT)
            return lines.join('\n')
        },

        show(target, sessionScopes) {
            const key = target.toLowerCase()

            const method = methodsById.get(key)
            if (method) {
                const header = methodLine(method, sessionScopes)
                const headerTokens = Math.ceil((header.length + method.description.length) / 4)
                const { included, truncated } = fillTypes(
                    method.referencedTypes,
                    Math.max(0, TYPES_SHOW_TOKEN_BUDGET - headerTokens)
                )
                return [header, method.description, ...renderTypeSection(included, truncated)]
                    .filter((part) => part.length > 0)
                    .join('\n\n')
            }

            const type = typesByName.get(key)
            if (type) {
                // The requested declaration always ships in full — the budget only
                // constrains the related types pulled in around it.
                const { included, truncated } = fillTypes(
                    type.referencedTypes,
                    Math.max(0, TYPES_SHOW_TOKEN_BUDGET - type.tokens)
                )
                return [type.declaration, ...renderTypeSection(included, truncated)].join('\n\n')
            }

            const domainMethods = index.methods.filter((candidate) => candidate.id.toLowerCase().startsWith(`${key}.`))
            if (domainMethods.length > 0) {
                const header = domainMethods.map((candidate) => methodLine(candidate, sessionScopes)).join('\n')
                const headerTokens = Math.ceil(header.length / 4)
                const seedRefs = domainMethods.flatMap((candidate) => candidate.referencedTypes)
                const { included, truncated } = fillTypes(seedRefs, Math.max(0, TYPES_SHOW_TOKEN_BUDGET - headerTokens))
                return [header, ...renderTypeSection(included, truncated)].join('\n\n')
            }

            throw new Error(`Unknown symbol "${target}". Run "types <query>" to search the SDK surface.`)
        },
    }
}

let generatedIndex: DiscoveryIndex | null = null

/**
 * The generated discovery index, loaded lazily — the artifact is megabytes of
 * JSON, and only the code-execution verbs read it.
 */
export async function getGeneratedDiscoveryIndex(): Promise<DiscoveryIndex> {
    if (!generatedIndex) {
        const module = await import('@/generated/code-exec/discovery-index.json')
        generatedIndex = module.default as unknown as DiscoveryIndex
    }
    return generatedIndex
}
