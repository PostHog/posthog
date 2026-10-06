import { MAX_SANKEY_COLUMN } from '@posthog/quill-charts'
import type { SankeyLinkInput, SankeyNodeInput } from '@posthog/quill-charts'

// This module imports nothing from `~/` or `lib/`, so the MCP UI app bundle, which only resolves
// `products/*` and `@posthog/*`, shares it with the paths insight.

/** The fields of a paths result row that the insight and the MCP app both read. */
export interface PathsEdge {
    source: string
    target: string
    value?: number | null
    average_conversion_time?: number | null
}

const STEP_PREFIX = /^(\d+)_/

/** Node keys are `<step>_<name>` with the step counted from 1. A key without a step prefix is
 *  step 0 and keeps its whole text as the name. */
export function parsePathNodeKey(key: string): { step: number; name: string } {
    const match = key.match(STEP_PREFIX)
    if (!match) {
        return { step: 0, name: key }
    }
    return { step: Number(match[1]), name: key.slice(match[0].length) }
}

/** Every node key once, in the order the result first names it. */
export function pathNodeKeys(edges: PathsEdge[]): string[] {
    const keys = new Set<string>()
    for (const edge of edges) {
        keys.add(edge.source)
        keys.add(edge.target)
    }
    return [...keys]
}

/** A page URL, or null. `new URL` also accepts any `word:` prefix, so an event named
 *  `clicked: signup` would otherwise lose its prefix as a pathless URL. */
function parseUrl(value: string): URL | null {
    try {
        const url = new URL(value)
        return url.protocol === 'http:' || url.protocol === 'https:' ? url : null
    } catch {
        return null
    }
}

/** The origin of every URL among the node names, so a caller can tell if the paths leave one site. */
export function pathOrigins(names: string[]): Set<string> {
    const origins = new Set<string>()
    for (const name of names) {
        const url = parseUrl(name)
        if (url) {
            origins.add(url.origin)
        }
    }
    return origins
}

/** A page URL as a short label: its path on a single origin, else its host and path. A hash stays
 *  when it looks like a route, so two steps that differ only there keep distinct labels. A name
 *  that is not a URL (an event name) comes back unchanged. */
export function pathUrlLabel(name: string, singleOrigin: boolean): string {
    const url = parseUrl(name)
    if (!url) {
        return name
    }
    const route = url.hash.includes('/') ? url.hash : ''
    const path = `${url.pathname}${url.search}${route}`
    return singleOrigin ? path || name : `${url.host}${path}`
}

/** Paths that begin at step 1: the flow out of that step. The query counts one path per person
 *  and session, so this is not a count of distinct people. Count it on the full result, because a
 *  truncated one drops the edges that show a later step is not a start. */
export function pathStartCount(edges: PathsEdge[]): number {
    return edges
        .filter((edge) => parsePathNodeKey(edge.source).step === 1)
        .reduce((sum, edge) => sum + (edge.value ?? 0), 0)
}

export interface PathsSankeyGraph<Edge extends PathsEdge> {
    nodes: SankeyNodeInput<string>[]
    links: SankeyLinkInput<Edge>[]
    /** The highest step in the result. */
    stepCount: number
    /** Whether nodes sit in their step's column, so the caller can label columns by step. False
     *  when pinning was off or the result has more steps than the chart has columns. */
    stepsPinned: boolean
}

export interface PathsSankeyGraphOptions {
    /** Short labels for page URLs. Off for a host that draws its own labels. */
    labelUrls?: boolean
    /** Pin each node to its step's column, so a path that ends early or an edge whose earlier steps
     *  were cut still sits under the right step. */
    pinSteps?: boolean
    nodeColor?: (key: string) => string | undefined
    linkColor?: string
}

/** Chart inputs for a paths result: one node per `<step>_<name>` key, so a page seen at two steps
 *  is two nodes. Node `meta` is the name without its step; link `meta` is the result row. */
export function buildPathsSankeyGraph<Edge extends PathsEdge>(
    edges: Edge[],
    { labelUrls = false, pinSteps = false, nodeColor, linkColor }: PathsSankeyGraphOptions = {}
): PathsSankeyGraph<Edge> {
    const keys = pathNodeKeys(edges)
    const parsed = keys.map((key) => ({ key, ...parsePathNodeKey(key) }))
    const singleOrigin = labelUrls && pathOrigins(parsed.map(({ name }) => name)).size <= 1
    const stepCount = parsed.reduce((max, { step }) => Math.max(max, step), 0)
    const stepsPinned = pinSteps && stepCount - 1 <= MAX_SANKEY_COLUMN

    const nodes = parsed.map(
        ({ key, step, name }): SankeyNodeInput<string> => ({
            id: key,
            label: labelUrls ? pathUrlLabel(name, singleOrigin) : undefined,
            color: nodeColor?.(key),
            meta: name,
            column: stepsPinned ? Math.max(0, step - 1) : undefined,
        })
    )
    const links = edges.map(
        (edge): SankeyLinkInput<Edge> => ({
            source: edge.source,
            target: edge.target,
            value: edge.value ?? 0,
            color: linkColor,
            meta: edge,
        })
    )
    return { nodes, links, stepCount, stepsPinned }
}
