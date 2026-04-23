import type { GroupType } from '@/api/client'
import { formatPrompt } from '@/lib/utils'
import type { CachedOrg, CachedProject, CachedUser } from '@/tools/types'

export function buildDefinedGroupsBlock(groupTypes?: GroupType[]): string {
    if (!groupTypes || groupTypes.length === 0) {
        return ''
    }
    return groupTypes.map((gt) => gt.group_type).join(', ')
}

export function buildActiveEnvironmentContextPrompt(
    user?: CachedUser,
    org?: CachedOrg,
    project?: CachedProject
): string | undefined {
    if (!user && !org && !project) {
        return undefined
    }
    const lines: string[] = []
    if (org || project) {
        const projectName = project?.name ?? 'Unknown'
        const projectId = project?.id ?? 'unknown'
        const orgName = org?.name ?? 'Unknown'
        const orgId = org?.id ?? 'unknown'
        lines.push(
            `You are currently in project "${projectName}" (id: ${projectId}) within organization "${orgName}" (id: ${orgId}).`
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
    return `### Active environment\n\nAll tool calls and queries are scoped to this environment.\n\n${lines.join('\n')}`
}

export function buildInstructionsV1(template: string, metadata?: string): string {
    if (!metadata) {
        return template
    }
    return `${template}\n\n${metadata}`
}

export interface ToolInfo {
    name: string
    category: string
}

/**
 * Extracts unique tool domain prefixes from a list of tools, collapsing CRUD
 * variations into their shared domain while keeping standalone/meta tools as-is.
 *
 * For example: experiment-create, experiment-get, experiment-delete → "experiment"
 * But: execute-sql, read-data-schema → listed individually (no action to strip)
 * And: query-* tools are excluded (documented separately in the prompt).
 */
export class ToolDomainExtractor {
    private static readonly PREFIX_ACTIONS = new Set(['create', 'update', 'delete', 'get'])

    private static readonly ACTION_SUFFIXES = new Set([
        'get',
        'get-all',
        'get-definition',
        'list',
        'create',
        'update',
        'delete',
        'retrieve',
        'destroy',
        'partial-update',
    ])

    private static readonly SKIP_CATEGORIES = new Set(['Query wrappers', 'Debug'])
    private static readonly MAX_DOMAIN_HYPHENS = 2

    private readonly standaloneTools = new Set<string>()
    private readonly derivedDomains = new Set<string>()

    constructor(tools: ToolInfo[]) {
        const byCategory = this.groupByCategory(tools)
        this.extractDomainsPerCategory(byCategory)
    }

    getDomains(): string[] {
        const collapsed = this.collapseDomains()
        const final = new Set(collapsed)

        for (const s of this.standaloneTools) {
            const covered = [...collapsed].some((d) => s.startsWith(d + '-') || s.startsWith(d + 's-'))
            if (!covered) {
                final.add(s)
            }
        }

        return [...final].sort()
    }

    toMarkdown(): string {
        return this.getDomains()
            .map((d) => `- ${d}`)
            .join('\n')
    }

    private groupByCategory(tools: ToolInfo[]): Map<string, string[]> {
        const byCategory = new Map<string, string[]>()
        for (const { name, category } of tools) {
            if (name.startsWith('query-') || ToolDomainExtractor.SKIP_CATEGORIES.has(category)) {
                continue
            }
            const names = byCategory.get(category) ?? []
            names.push(name)
            byCategory.set(category, names)
        }
        return byCategory
    }

    private extractDomainsPerCategory(byCategory: Map<string, string[]>): void {
        for (const [, names] of byCategory) {
            const standalones = names.filter((n) => ToolDomainExtractor.stripAction(n) === n)

            if (standalones.length === names.length) {
                for (const n of names) {
                    this.standaloneTools.add(n)
                }
                continue
            }

            for (const n of standalones) {
                this.standaloneTools.add(n)
            }

            const stems = [
                ...new Set(
                    names
                        .filter((n) => ToolDomainExtractor.stripAction(n) !== n)
                        .map((n) => ToolDomainExtractor.stripAction(n))
                ),
            ].sort()

            if (stems.length === 1 && stems[0]) {
                this.derivedDomains.add(stems[0])
            } else if (stems.length > 1) {
                const cp = ToolDomainExtractor.commonPrefix(stems)
                if (cp && cp.length >= 3) {
                    this.derivedDomains.add(cp)
                } else {
                    for (const s of stems) {
                        this.derivedDomains.add(s)
                    }
                }
            }
        }
    }

    private collapseDomains(): Set<string> {
        const collapsed = new Set<string>()
        for (const d of [...this.derivedDomains].sort((a, b) => a.length - b.length)) {
            if ((d.match(/-/g) ?? []).length > ToolDomainExtractor.MAX_DOMAIN_HYPHENS) {
                continue
            }
            const dominated = [...collapsed].some(
                (ex) => ToolDomainExtractor.isPlural(d, ex) || d.startsWith(ex + '-') || d.startsWith(ex + 's-')
            )
            if (!dominated) {
                collapsed.add(d)
            }
        }
        return collapsed
    }

    static stripAction(name: string): string {
        let parts = name.split('-')

        if (parts[0] && ToolDomainExtractor.PREFIX_ACTIONS.has(parts[0]) && parts.length > 1) {
            parts = parts.slice(1)
        }

        for (const len of [4, 3, 2, 1]) {
            if (parts.length > len) {
                const suffix = parts.slice(-len).join('-')
                if (ToolDomainExtractor.ACTION_SUFFIXES.has(suffix)) {
                    return parts.slice(0, -len).join('-')
                }
            }
        }

        return parts.join('-')
    }

    private static commonPrefix(strings: string[]): string {
        if (strings.length === 0 || !strings[0]) {
            return ''
        }
        let prefix: string = strings[0]
        for (const s of strings.slice(1)) {
            while (prefix && !s.startsWith(prefix)) {
                prefix = prefix.slice(0, -1)
            }
            if (!prefix) {
                return ''
            }
        }
        const allAtBoundary = strings.every(
            (s) =>
                s.length === prefix.length ||
                s[prefix.length] === '-' ||
                (s[prefix.length] === 's' && s[prefix.length + 1] === '-')
        )
        if (!allAtBoundary) {
            const idx = prefix.lastIndexOf('-')
            return idx > 0 ? prefix.slice(0, idx) : prefix
        }
        return prefix
    }

    private static isPlural(a: string, b: string): boolean {
        return a + 's' === b || b + 's' === a
    }
}

export function buildToolDomainsBlock(tools: ToolInfo[]): string {
    return new ToolDomainExtractor(tools).toMarkdown()
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
        const queryTools = this.tools
            .filter((t) => t.name.startsWith('query-'))
            .sort((a, b) => a.name.localeCompare(b.name))
        if (queryTools.length === 0) {
            return ''
        }
        return queryTools.map((t) => `- \`${t.name}\` — ${t.systemPromptHint ?? t.title}`).join('\n')
    }
}

export function buildQueryToolsBlock(tools: QueryToolInfo[]): string {
    return new QueryToolCatalog(tools).toMarkdown()
}

export function buildInstructionsV2(
    template: string,
    guidelines: string,
    groupTypes?: GroupType[],
    metadata?: string,
    tools?: ToolInfo[],
    queryTools?: QueryToolInfo[]
): string {
    return formatPrompt(template, {
        guidelines: guidelines.trim(),
        defined_groups: buildDefinedGroupsBlock(groupTypes),
        metadata: metadata?.trim() ?? '',
        tool_domains: tools ? buildToolDomainsBlock(tools) : '',
        query_tools: queryTools ? buildQueryToolsBlock(queryTools) : '',
    })
}
