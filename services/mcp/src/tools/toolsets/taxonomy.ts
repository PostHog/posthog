/**
 * Progressive disclosure taxonomy.
 *
 * **Base toolsets** are auto-derived from the `feature` field on every tool definition
 * (which comes from `products/<name>/mcp/tools.yaml` via codegen). No hand-edits needed
 * when a new product ships MCP tools — adding a new `feature` value in a YAML automatically
 * creates a new base toolset with the product's category as its title.
 *
 * **Composite toolsets** are a small, hand-curated editorial layer that bundles related
 * base toolsets into convenience groupings (e.g., `analytics` = insights + events + cohorts
 * + actions + persons + product_analytics). Enabling a composite is equivalent to enabling
 * every base toolset it contains. Composites are optional — the model can always enable
 * base toolsets directly.
 *
 * **Excluded features** are either bootstrap (`docs`, `search`), internal (`debug`,
 * `skills`, `meta`), or otherwise never surfaced as a standalone toolset.
 */

import { getToolDefinitions } from '@/tools/toolDefinitions'

/** Tools always available in progressive mode regardless of enabled toolsets. */
export const BOOTSTRAP_TOOL_NAMES = ['query-run', 'docs-search', 'entity-search', 'toolsets'] as const

/**
 * Features that should NOT appear as base toolsets. Either their tools are bootstrap
 * (docs, search), or they're internal/meta and not user-addressable.
 */
const EXCLUDED_FEATURES = new Set(['docs', 'search', 'debug', 'skills', 'meta'])

/**
 * Optional composite toolsets. Each bundles multiple base features into one enable/disable
 * action for convenience. This is the only hand-curated part of the taxonomy — decisions
 * about what belongs together are editorial, not mechanical.
 *
 * Keep the set small (≤10) and focused on workflows a single prompt might touch. When in
 * doubt, leave it out and let the model enable base toolsets directly.
 */
export const COMPOSITE_TOOLSETS: Record<string, { title: string; description: string; features: string[] }> = {
    analytics: {
        title: 'Analytics (bundle)',
        description:
            'Insights, events, cohorts, actions, persons, and product analytics — everything needed for trends, funnels, retention, and event/property discovery.',
        features: ['insights', 'events', 'cohorts', 'actions', 'persons', 'product_analytics'],
    },
    content: {
        title: 'Dashboards, notebooks, annotations (bundle)',
        description:
            'Dashboards, notebooks, and annotations — for building and annotating the artifacts that get shared.',
        features: ['dashboards', 'notebooks', 'annotations'],
    },
    admin: {
        title: 'Admin / workspace (bundle)',
        description:
            'Orgs, projects, platform admin, integrations, alerts — the primitives needed to manage a PostHog instance. Enable this first if the model cannot tell which project/org to operate on.',
        features: ['workspace', 'core', 'platform_features', 'integrations', 'alerts'],
    },
}

export type ToolsetDefinition = {
    id: string
    title: string
    description: string
    /** Feature IDs this toolset covers (1 element for base, multiple for composites). */
    features: string[]
    /** True when derived directly from a tool `feature` value; false for composites. */
    isBase: boolean
}

/**
 * Build the full toolset list for a given MCP version. Base toolsets come from the tool
 * catalog's distinct `feature` values; composites come from COMPOSITE_TOOLSETS above.
 */
export function getAllToolsets(version?: number): ToolsetDefinition[] {
    const defs = getToolDefinitions(version)
    const base: Record<string, { category: string; toolCount: number }> = {}

    for (const meta of Object.values(defs)) {
        const feature = meta.feature
        if (!feature || EXCLUDED_FEATURES.has(feature)) {
            continue
        }
        if (!base[feature]) {
            base[feature] = { category: meta.category, toolCount: 0 }
        }
        base[feature].toolCount++
    }

    const baseToolsets: ToolsetDefinition[] = Object.entries(base)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([id, { category, toolCount }]) => ({
            id,
            title: category,
            description: `${category} tools (${toolCount}).`,
            features: [id],
            isBase: true,
        }))

    const compositeToolsets: ToolsetDefinition[] = Object.entries(COMPOSITE_TOOLSETS).map(
        ([id, { title, description, features }]) => ({
            id,
            title,
            description,
            features,
            isBase: false,
        })
    )

    return [...baseToolsets, ...compositeToolsets]
}

export function getToolsetById(id: string, version?: number): ToolsetDefinition | undefined {
    return getAllToolsets(version).find((ts) => ts.id === id)
}

export function isValidToolsetId(id: string, version?: number): boolean {
    return getAllToolsets(version).some((ts) => ts.id === id)
}

export function isBootstrapTool(name: string): boolean {
    return (BOOTSTRAP_TOOL_NAMES as readonly string[]).includes(name)
}

/**
 * Expand a toolset id to the concrete set of feature IDs it unlocks. For base toolsets
 * this is [id]; for composites it's the feature list.
 */
export function expandToolsetToFeatures(id: string, version?: number): string[] {
    const ts = getToolsetById(id, version)
    return ts ? ts.features : []
}

/**
 * Given a set of enabled toolset ids (mixed base/composite), return the flat set of
 * feature ids that should be surfaced. Unknown ids are silently ignored.
 */
export function resolveEnabledFeatures(enabledToolsets: readonly string[], version?: number): Set<string> {
    const out = new Set<string>()
    for (const id of enabledToolsets) {
        for (const feature of expandToolsetToFeatures(id, version)) {
            out.add(feature)
        }
    }
    return out
}
