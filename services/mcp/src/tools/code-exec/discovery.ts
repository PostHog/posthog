/**
 * SDK surface discovery for the `types` exec verb. One verb, two modes,
 * disambiguated by exactness: when every whitespace/comma-separated token of
 * the input resolves exactly (method id → type name → domain prefix) the verb
 * fetches exactly those declarations; otherwise the whole input is one search
 * pattern. Fetch responses stay lean — referenced types surface as hints, not
 * inlined bodies — and are hard-capped at `TYPES_CHAR_LIMIT`, with every
 * truncation naming the follow-up call. Both modes run over the generated
 * discovery index (a codegen-time artifact), never over runtime type-walking.
 * Results are scope-annotated per session so agents know before writing a
 * script which methods their token can call.
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
    /** Direct references only. */
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
 * Hard cap on one `types` response. Fetches include whole declarations in
 * request order while they fit; anything cut is named in a truncation hint so
 * the agent can fetch it in a follow-up call — the response never exceeds the
 * cap (roughly half the exec layer's serialized-response cap).
 */
export const TYPES_CHAR_LIMIT = 24_000

const FETCH_HINT =
    'Run "types <TypeName | domain.method | domain>" — exact names (several allowed, space-separated) return full declarations.'

export interface Discovery {
    resolve(input: string, sessionScopes: string[]): string
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

function referencesHint(referencedTypes: string[]): string {
    if (referencedTypes.length === 0) {
        return ''
    }
    return `References — run "types ${referencedTypes.join(' ')}" for declarations`
}

type ResolvedTarget =
    | { kind: 'method'; key: string; method: DiscoveryMethod }
    | { kind: 'type'; key: string; type: DiscoveryType }
    | { kind: 'domain'; key: string; domain: string; methods: DiscoveryMethod[] }

/** One renderable unit of a fetch response, with what a truncation hint needs. */
interface FetchSection {
    label: string
    text: string
    referencedTypes: string[]
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

    const resolveExact = (token: string): ResolvedTarget | null => {
        const key = token.toLowerCase()
        const method = methodsById.get(key)
        if (method) {
            return { kind: 'method', key: `method:${key}`, method }
        }
        const type = typesByName.get(key)
        if (type) {
            return { kind: 'type', key: `type:${key}`, type }
        }
        const domainMethods = index.methods.filter((candidate) => candidate.id.toLowerCase().startsWith(`${key}.`))
        if (domainMethods.length > 0) {
            return { kind: 'domain', key: `domain:${key}`, domain: token, methods: domainMethods }
        }
        return null
    }

    const toSection = (target: ResolvedTarget, sessionScopes: string[]): FetchSection => {
        switch (target.kind) {
            case 'type':
                return {
                    label: target.type.name,
                    text: [target.type.declaration, referencesHint(target.type.referencedTypes)]
                        .filter((part) => part.length > 0)
                        .join('\n\n'),
                    referencedTypes: target.type.referencedTypes,
                }
            case 'method':
                return {
                    label: target.method.id,
                    text: [
                        methodLine(target.method, sessionScopes),
                        target.method.description,
                        referencesHint(target.method.referencedTypes),
                    ]
                        .filter((part) => part.length > 0)
                        .join('\n\n'),
                    referencedTypes: target.method.referencedTypes,
                }
            case 'domain':
                return {
                    label: target.domain,
                    text: target.methods.map((method) => methodLine(method, sessionScopes)).join('\n'),
                    referencedTypes: [],
                }
        }
    }

    /**
     * Assemble sections in request order under the char cap. The first section
     * always ships (hard-truncated if it alone exceeds the cap, pointing at its
     * referenced types); once a later section doesn't fit, it and everything
     * after it are omitted by name so the agent can fetch them separately.
     */
    const renderFetch = (targets: ResolvedTarget[], sessionScopes: string[]): string => {
        const seen = new Set<string>()
        const sections: FetchSection[] = []
        for (const target of targets) {
            if (seen.has(target.key)) {
                continue
            }
            seen.add(target.key)
            sections.push(toSection(target, sessionScopes))
        }

        const parts: string[] = []
        const omitted: string[] = []
        let used = 0
        for (const [i, section] of sections.entries()) {
            if (omitted.length > 0) {
                omitted.push(section.label)
                continue
            }
            const cost = section.text.length + (parts.length > 0 ? 2 : 0)
            if (used + cost <= TYPES_CHAR_LIMIT) {
                parts.push(section.text)
                used += cost
                continue
            }
            if (i === 0) {
                const refsNote =
                    section.referencedTypes.length > 0
                        ? ` — fetch its parts via the referenced types: ${section.referencedTypes.join(', ')}`
                        : ''
                parts.push(
                    `${section.text.slice(0, TYPES_CHAR_LIMIT)}\n…[declaration truncated at ${TYPES_CHAR_LIMIT} chars${refsNote}]`
                )
                used = TYPES_CHAR_LIMIT
            } else {
                omitted.push(section.label)
            }
        }
        if (omitted.length > 0) {
            parts.push(
                `Omitted (${TYPES_CHAR_LIMIT} char cap): ${omitted.join(', ')} — request them in a separate "types" call.`
            )
        }
        return parts.join('\n\n')
    }

    const search = (query: string, sessionScopes: string[]): string => {
        if (query.length > MAX_TYPES_PATTERN_LENGTH) {
            throw new Error(
                `Search pattern too long (${query.length} chars, max ${MAX_TYPES_PATTERN_LENGTH}). Use a shorter, more targeted pattern.`
            )
        }
        // The compiled regex carries no `g`/`y` flag, so it is stateless and
        // safe to reuse across candidates.
        const matcher = buildMatcher(query)
        const methodMatches = index.methods.filter(
            (method) =>
                matcher(method.id) ||
                matcher(method.signature) ||
                matcher(method.title) ||
                matcher(method.description) ||
                method.referencedTypes.some(matcher)
        )
        const typeMatches = index.types.filter((type) => matcher(type.name)).map((type) => type.name)
        if (methodMatches.length === 0 && typeMatches.length === 0) {
            return `No SDK methods or types matched "${query}". Try a broader pattern, or "types <domain>" for a whole resource.`
        }

        const lines: string[] = []
        const shown = methodMatches.slice(0, MAX_SEARCH_RESULTS)
        const byCategory = new Map<string, DiscoveryMethod[]>()
        for (const method of shown) {
            const group = byCategory.get(method.category)
            if (group) {
                group.push(method)
            } else {
                byCategory.set(method.category, [method])
            }
        }
        for (const [category, methods] of byCategory) {
            lines.push(`${category}:`)
            for (const method of methods) {
                lines.push(`  ${methodLine(method, sessionScopes)}`)
            }
        }
        if (methodMatches.length > shown.length) {
            lines.push(
                '',
                `Showing ${shown.length} of ${methodMatches.length} matches — refine the query to see the rest.`
            )
        }
        if (typeMatches.length > 0) {
            const shownTypes = typeMatches.slice(0, MAX_SEARCH_RESULTS)
            const more =
                typeMatches.length > shownTypes.length ? `, … ${typeMatches.length - shownTypes.length} more` : ''
            lines.push('', 'Types:', `  ${shownTypes.join(', ')}${more}`)
        }
        lines.push('', FETCH_HINT)
        return lines.join('\n')
    }

    return {
        resolve(input, sessionScopes) {
            const trimmed = input.trim()
            // Compatibility with the retired `types show <targets>` sub-verb.
            const effective = /^show\s+\S/i.test(trimmed) ? trimmed.replace(/^show\s+/i, '') : trimmed
            const tokens = effective.split(/[\s,]+/).filter((token) => token.length > 0)
            const resolved: ResolvedTarget[] = []
            let allExact = tokens.length > 0
            for (const token of tokens) {
                const target = resolveExact(token)
                if (!target) {
                    allExact = false
                    break
                }
                resolved.push(target)
            }
            if (allExact) {
                return renderFetch(resolved, sessionScopes)
            }
            return search(effective, sessionScopes)
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
