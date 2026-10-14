// Ceiling for the tool-domain index inside the claude.ai exec command reference. That reference
// lives in the `command` description, whose serialized schema claude.ai silently drops past
// ~16,384 chars, and the index is the only part of it that grows with the tool catalog — one new
// tool can split a family into sub-family roots and add hundreds of characters. Bounding it here
// makes `toCompact` trade sub-family precision to stay inside the cap, which costs far less than
// a dropped exec tool.
export const MCP_CLAUDE_TOOL_DOMAINS_CHAR_BUDGET = 1536

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
     *  while breaking up large multi-family areas (e.g. AI observability).
     *
     *  This is the preferred split, not a hard one: {@link toCompact} raises the
     *  threshold when the rendered index has to fit a character budget, trading
     *  sub-family precision for keeping every family represented. */
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
        'accept',
        'archive',
        'calculate',
        'cancel',
        'claim',
        'complete',
        'compose',
        'copy',
        'disable',
        'discard',
        'dismiss',
        'duplicate',
        'edit',
        'emit',
        'enable',
        'end',
        'estimate',
        'fail',
        'freeze',
        'launch',
        'migrate',
        'move',
        'patch',
        'pause',
        'publish',
        'record',
        'rename',
        'reset',
        'restore',
        'resume',
        'ship',
        'show',
        'start',
        'suggest',
        'test',
        'transfer',
        'unarchive',
        'unfreeze',
        'upload',
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

    getDomains(maxFamilySize: number = ToolDomainExtractor.MAX_FAMILY_SIZE): string[] {
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
            this.cut(bucket, 1, domains, maxFamilySize)
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

    /**
     * Render the index as a single pipe-delimited line, collapsing sub-families
     * until it fits `maxChars`.
     *
     * The index is a routing hint — every domain is a literal tool-name prefix
     * that `search` expands — so `scout` costs 120 fewer characters than its ten
     * `scout-*` roots and still reaches the same tools. Dropping precision is
     * therefore much cheaper than dropping domains, which is what a client-side
     * truncation does: the list is alphabetical, so an overrun silently deletes
     * the tail (every `scout`, `survey`, `workflows`, `web-analytics` domain)
     * while the model has no way to know they exist.
     *
     * Raising the family-size threshold only ever merges families, so the
     * rendered length decreases monotonically and doubling converges quickly.
     * The floor is one domain per root; if even that overruns, the caller gets
     * the too-long string rather than a silently trimmed one.
     */
    toCompact(maxChars?: number): string {
        let maxFamilySize = ToolDomainExtractor.MAX_FAMILY_SIZE
        for (;;) {
            const rendered = this.getDomains(maxFamilySize).join('|')
            if (maxChars === undefined || rendered.length <= maxChars || maxFamilySize >= this.items.length) {
                return rendered
            }
            maxFamilySize *= 2
        }
    }

    /** Reduce a group sharing a `depth`-segment prefix to one or more domains,
     *  splitting only when the group is too large to scan in one search. */
    private cut(group: ToolItem[], depth: number, out: Set<string>, maxFamilySize: number): void {
        depth = this.compressUnary(group, depth)
        if (group.length <= maxFamilySize) {
            out.add(this.render(group, depth))
            return
        }
        for (const [childKey, childGroup] of this.childrenBySegment(group, depth)) {
            if (childKey === null || childGroup.length <= maxFamilySize) {
                out.add(this.render(childGroup, depth + 1))
            } else {
                this.cut(childGroup, depth + 1, out, maxFamilySize)
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

export function buildToolDomainsCompact(tools: ToolInfo[], maxChars?: number): string {
    return new ToolDomainExtractor(tools).toCompact(maxChars)
}
