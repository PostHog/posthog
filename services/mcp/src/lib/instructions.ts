import type { GroupType } from '@/api/client'
import type { CachedOrg, CachedProject, CachedUser } from '@/tools/types'

export function buildDefinedGroupsBlock(groupTypes?: GroupType[]): string {
    if (!groupTypes || groupTypes.length === 0) {
        return ''
    }
    return `Defined group types: ${groupTypes.map((gt) => gt.group_type).join(', ')}`
}

export function buildActiveEnvironmentContextPrompt(
    user?: CachedUser,
    org?: CachedOrg,
    project?: CachedProject,
    regionalBaseUrl?: string
): string | undefined {
    if (!user && !org && !project) {
        return undefined
    }
    const lines: string[] = []
    if (org || project) {
        const projectName = project?.name ?? 'Unknown'
        const projectId = project?.id ?? 'unknown'
        const projectToken = project?.api_token ?? 'unknown'

        if (org) {
            const orgName = org.name ?? 'Unknown'
            const orgId = org.id ?? 'unknown'
            lines.push(
                `You are currently in project "${projectName}" (id: ${projectId}, token: ${projectToken}) within organization "${orgName}" (id: ${orgId}).`
            )
        } else {
            lines.push(`You are currently in project "${projectName}" (id: ${projectId}, token: ${projectToken}).`)
        }
    }
    if (regionalBaseUrl) {
        const origin = regionalBaseUrl.replace(/^https?:\/\//, '')
        lines.push(
            project?.id !== undefined
                ? `Base URL: ${origin} — add /project/${project.id} for project-scoped paths.`
                : `Base URL: ${origin}.`
        )
    }
    if (project) {
        lines.push(`Project timezone: ${project.timezone ?? 'UTC'}.`)
        const poeValue = project.person_on_events_querying_enabled as string | boolean | null | undefined
        if (poeValue === true || poeValue === 'true') {
            lines.push(
                'Person-on-events mode is enabled. When querying `person.properties.*` on the events table, values reflect what was set at the time the event was ingested, not the person\'s current value. The same person can have different property values across different events. Do not suggest workarounds for "query-time" person properties.'
            )
        } else {
            lines.push(
                "Person properties are query-time in this project. `person.properties.*` on the events table always returns the person's current (latest) value, regardless of when the event occurred."
            )
        }
    }
    if (user) {
        const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ') || 'Unknown'
        lines.push(`The user's name is ${fullName} (${user.email}).`)
    }
    return `### Active environment\n\nAll tool calls and queries default to this environment; you can switch projects or organizations at any time.\n\n${lines.join('\n')}`
}

export interface ToolInfo {
    name: string
    category: string
}

interface ToolItem {
    /** Tool name split on `-`, with a leading CRUD verb dropped. */
    segments: string[]
    /** `segments` with each part singularized — the key used for grouping so
     *  `feature-flag` and `feature-flags` land in the same family. */
    key: string[]
}

/**
 * Reduces a tool list to a compact set of name-prefix "domains" that seed the
 * agent's `exec search <regex>` discovery (search matches name/title/description,
 * so every emitted domain is a literal tool-name prefix and is guaranteed to
 * retrieve its family).
 *
 * Tools are grouped globally (not per-category) by a radix tree over their name
 * segments. A family stays a single domain while it is small enough to scan in
 * one search ({@link MAX_FAMILY_SIZE}); oversized families are split into their
 * sub-family roots one level deeper. So:
 *   - experiment-create / experiment-get / … → "experiment" (one flat family)
 *   - all 60+ llma-* tools → "llma-evaluation" | "llma-skill" | "llma-prompt" | …
 *   - external-data-schemas-* / external-data-sources-* → "external-data"
 *   - feature-flag-* / feature-flags-* → "feature-flag" (singular/plural merged)
 * All query-* tools collapse to a single "query" domain (`search query-` lists
 * them); their typed catalog is documented separately in the prompt.
 */
export class ToolDomainExtractor {
    /** A family at or below this many tools stays one domain; above it, split
     *  into sub-family roots. ~25 keeps flat CRUD families (e.g. experiment) whole
     *  while breaking up large multi-family areas (e.g. AI observability). */
    private static readonly MAX_FAMILY_SIZE = 25
    /** Cap on rendered segments so a singleton/leaf family becomes a short
     *  domain (`activity-log`) rather than its full tool name. */
    private static readonly MAX_DOMAIN_SEGMENTS = 3

    private static readonly SKIP_CATEGORIES = new Set(['Query wrappers', 'Debug'])
    /** Stripped from the front so `get-llm-total-costs` joins the `llm` family
     *  instead of a spurious `get` family. */
    private static readonly LEADING_VERBS = new Set([
        'get',
        'create',
        'update',
        'delete',
        'list',
        'retrieve',
        'destroy',
    ])
    /** Trimmed off the end of a rendered domain (only ever present on a
     *  singleton family, whose prefix runs to the trailing action). */
    private static readonly TRAILING_ACTIONS = new Set([
        'get',
        'list',
        'create',
        'update',
        'delete',
        'retrieve',
        'destroy',
        'run',
    ])

    private readonly items: ToolItem[]
    /** query-* tools are kept out of the trie and represented by a single
     *  `query` domain, so the catalog never fragments into per-insight roots. */
    private readonly hasQueryTools: boolean

    constructor(tools: ToolInfo[]) {
        this.hasQueryTools = tools.some(({ name }) => name.startsWith('query-'))
        this.items = tools
            .filter(
                ({ name, category }) => !name.startsWith('query-') && !ToolDomainExtractor.SKIP_CATEGORIES.has(category)
            )
            .map(({ name }) => {
                const segments = ToolDomainExtractor.toSegments(name)
                return { segments, key: segments.map(ToolDomainExtractor.singularize) }
            })
    }

    getDomains(): string[] {
        const byRoot = new Map<string, ToolItem[]>()
        for (const item of this.items) {
            const root = item.key[0]
            if (!root) {
                continue
            }
            const bucket = byRoot.get(root)
            if (bucket) {
                bucket.push(item)
            } else {
                byRoot.set(root, [item])
            }
        }
        const domains = new Set<string>()
        for (const bucket of byRoot.values()) {
            this.cut(bucket, 1, domains)
        }
        if (this.hasQueryTools) {
            domains.add('query')
        }
        return [...domains].sort()
    }

    toMarkdown(): string {
        return this.getDomains()
            .map((d) => `- ${d}`)
            .join('\n')
    }

    toCompact(): string {
        return this.getDomains().join('|')
    }

    /** Reduce a group sharing a `depth`-segment prefix to one or more domains,
     *  splitting only when the group is too large to scan in one search. */
    private cut(group: ToolItem[], depth: number, out: Set<string>): void {
        depth = this.compressUnary(group, depth)
        if (group.length <= ToolDomainExtractor.MAX_FAMILY_SIZE) {
            out.add(this.render(group, depth))
            return
        }
        for (const [childKey, childGroup] of this.childrenBySegment(group, depth)) {
            if (childKey === null || childGroup.length <= ToolDomainExtractor.MAX_FAMILY_SIZE) {
                out.add(this.render(childGroup, depth + 1))
            } else {
                this.cut(childGroup, depth + 1, out)
            }
        }
    }

    /** Advance `depth` past segments shared by the whole group (radix
     *  compression), so a unary chain like `external` → `external-data` is kept
     *  intact rather than emitted as a one-word root. */
    private compressUnary(group: ToolItem[], depth: number): number {
        for (;;) {
            if (group.some((it) => it.key.length <= depth)) {
                return depth
            }
            const next = new Set(group.map((it) => it.key[depth]))
            if (next.size !== 1) {
                return depth
            }
            depth++
        }
    }

    /** Partition a group by its segment at `depth`. Tools whose name ends at or
     *  before `depth` (the prefix is the whole tool) are keyed `null`. */
    private childrenBySegment(group: ToolItem[], depth: number): Map<string | null, ToolItem[]> {
        const children = new Map<string | null, ToolItem[]>()
        for (const item of group) {
            const key = item.key.length <= depth ? null : (item.key[depth] ?? null)
            const bucket = children.get(key)
            if (bucket) {
                bucket.push(item)
            } else {
                children.set(key, [item])
            }
        }
        return children
    }

    /** Render a group's shared `depth`-segment prefix as a domain string, using
     *  the shortest actual spelling at each position (so a singular/plural pair
     *  collapses to one searchable prefix) and trimming any trailing action. */
    private render(group: ToolItem[], depth: number): string {
        const length = Math.min(depth, ToolDomainExtractor.MAX_DOMAIN_SEGMENTS)
        const segments: string[] = []
        for (let i = 0; i < length; i++) {
            const forms = [...new Set(group.map((it) => it.segments[i]).filter((s): s is string => !!s))].sort(
                (a, b) => a.length - b.length
            )
            const shortest = forms[0]
            if (shortest) {
                segments.push(shortest)
            }
        }
        while (segments.length > 1 && ToolDomainExtractor.TRAILING_ACTIONS.has(segments[segments.length - 1] ?? '')) {
            segments.pop()
        }
        return segments.join('-')
    }

    private static toSegments(name: string): string[] {
        const parts = name.split('-')
        if (parts[0] && ToolDomainExtractor.LEADING_VERBS.has(parts[0]) && parts.length > 1) {
            return parts.slice(1)
        }
        return parts
    }

    private static singularize(segment: string): string {
        return segment.replace(/s$/, '')
    }
}

export function buildToolDomainsBlock(tools: ToolInfo[]): string {
    return new ToolDomainExtractor(tools).toMarkdown()
}

export function buildToolDomainsCompact(tools: ToolInfo[]): string {
    return new ToolDomainExtractor(tools).toCompact()
}

export interface QueryToolInfo {
    name: string
    title: string
    systemPromptHint?: string
}

/**
 * Renders the `query-*` tool catalog injected into the system prompt as a
 * single bullet list. Populated from the YAML `system_prompt_hint` field with
 * `title` as a fallback so a missing hint is visible rather than silent.
 */
export class QueryToolCatalog {
    constructor(private readonly tools: QueryToolInfo[]) {}

    toMarkdown(): string {
        const queryTools = this.filteredAndSorted()
        if (queryTools.length === 0) {
            return ''
        }
        return queryTools.map((t) => `- \`${t.name}\` — ${t.systemPromptHint ?? t.title}`).join('\n')
    }

    private filteredAndSorted(): QueryToolInfo[] {
        return this.tools.filter((t) => t.name.startsWith('query-')).sort((a, b) => a.name.localeCompare(b.name))
    }
}

export function buildQueryToolsBlock(tools: QueryToolInfo[]): string {
    return new QueryToolCatalog(tools).toMarkdown()
}
