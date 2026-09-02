import { UniversalFiltersGroup } from '~/types'

import { SEVERITY_BAR_COLORS } from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'

import { FacetOption } from './Facet'
import {
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    facetFilterTarget,
    innerFilters,
    isPropertyLeaf,
} from './facetFilters'

/**
 * Whether a facet's value set is known ahead of time or discovered from the data.
 *
 * - `fixed`: a closed enum defined here in code (e.g. severity levels). The full list is rendered
 *   regardless of the data; values with a zero count show dimmed rather than disappearing.
 * - `dynamic`: values come back from the data at query time (e.g. service names) and change with
 *   the active filters. Only values present in the current scope appear — zeros never show.
 */
export type FacetKind = 'fixed' | 'dynamic'

/** The ClickHouse column a column facet's values + counts are computed over (matches backend FACET_FIELDS). */
export type FacetField = 'severity_text' | 'service_name'

/**
 * Where a facet's field lives, which determines how its values are queried. Selection itself always
 * lives in the filterGroup, whatever the source, so the rail and the chips bar read and write one
 * store and can never disagree about what is filtered.
 *
 * - `column`: a top-level logs column, filtered through a `log` property filter under `logKey`.
 * - `resourceAttribute`: a `resource_attributes` map key (e.g. k8s.namespace.name), filtered through
 *   a `log_resource_attribute` property filter under `key`.
 * - `attribute`: a plain (non-resource) log attribute key, filtered through a `log_attribute`
 *   property filter under `key`. Only used by user-added custom facets today — no curated `FACETS`
 *   entry uses it.
 */
export type FacetSource =
    | {
          type: 'column'
          column: FacetField
          /**
           * The `log` property-filter key this facet's selection is stored under (severity_level for
           * the severity_text column). Must match the key LogsFilterBuilder.where() strips when
           * faceting on this column (products/logs/backend/logs_query_runner.py, pinned from the
           * other side by products/logs/backend/test/test_log_facet_values.py), or a selected value
           * would zero out its own count.
           */
          logKey: string
      }
    | { type: 'resourceAttribute'; key: string; aliasKeys?: string[] }
    | { type: 'attribute'; key: string }

export interface FacetConfig {
    /** Stable id used for collapse state and data-attrs. */
    key: string
    /** User-facing field name shown as the facet header. */
    title: string
    /** Header the facet is grouped under in the rail (e.g. "Standard"). */
    group: string
    kind: FacetKind
    source: FacetSource
    /** Required for `fixed` facets: the closed value set, with labels + colors. */
    fixedOptions?: FacetOption[]
    /** Renders a search box and virtualizes the list — for `dynamic` facets with many values. */
    searchable?: boolean
    searchPlaceholder?: string
    emptyLabel?: string
    /** Max pixel height before the value list virtualizes and scrolls. */
    maxHeight?: number
    /** The (key, sourceType) a user-added custom facet was built from; curated facets never set it. */
    custom?: { key: string; sourceType: CustomFacetSourceType }
}

/** The data key a facet is queried on: its column, or the resource-attribute key resolution picked. */
export function facetSourceKey(facet: FacetConfig): string {
    return facet.source.type === 'column' ? facet.source.column : facet.source.key
}

/** Everything a facet's own values can depend on, before its own selection is stripped out. */
export interface FacetScope {
    currentTeamId: number | null
    utcDateRange: { date_from?: string | null; date_to?: string | null; explicitDate?: boolean | null }
    searchTerm?: string | null
    /** filterGroup with pinned filters folded in — what the query actually carries. */
    queryFilterGroup: UniversalFiltersGroup | undefined
    personId?: string
}

/**
 * A stable string identifying everything that can change this facet's values: the query scope minus
 * the facet's own contributions, mirroring what the backend strips (exclude_facet_field /
 * exclude_resource_attribute). Selecting a value in this facet leaves the signature untouched, so the
 * facet doesn't refetch itself; selecting in any other facet changes it.
 *
 * A string, not an object: `filters` and `queryFilterGroup` get a fresh identity on every edit, so an
 * object couldn't tell "nothing I care about changed". Errs toward refetching — a dimension the
 * backend ignores still enters the signature — never toward serving stale counts.
 */
export function facetScopeSignature(facet: FacetConfig, scope: FacetScope): string {
    const { source } = facet
    // The facet's own filter target — the backend strips filters under it wholesale (any operator,
    // both polarities), so they must not enter the signature.
    const self = facetFilterTarget(source)
    const groupSignature = innerFilters(scope.queryFilterGroup)
        .map((entry): unknown[] | null => {
            if (!isPropertyLeaf(entry)) {
                // Nested groups aren't leaves the backend can strip — carry them whole.
                return ['group', JSON.stringify(entry)]
            }
            if (entry.type === self.type && entry.key === self.key) {
                return null
            }
            return [entry.type, entry.key, entry.operator, JSON.stringify(entry.value ?? null)]
        })
        .filter((entry) => entry !== null)

    return JSON.stringify([
        // A facet mounted before the team resolved fetches nothing; keeping the id in the signature
        // makes it fetch once the team arrives.
        scope.currentTeamId ?? null,
        [source.type, facetSourceKey(facet)],
        scope.utcDateRange.date_from ?? null,
        scope.utcDateRange.date_to ?? null,
        scope.utcDateRange.explicitDate ?? null,
        scope.searchTerm || null,
        scope.personId ?? null,
        groupSignature,
    ])
}

// Colors mirror the severity bar in the log rows (SEVERITY_BAR_COLORS) so the rail matches the viewer.
const SEVERITY_OPTIONS: FacetOption[] = (
    [
        ['trace', 'Trace'],
        ['debug', 'Debug'],
        ['info', 'Info'],
        ['warn', 'Warn'],
        ['error', 'Error'],
        ['fatal', 'Fatal'],
    ] as const
).map(([value, label]) => ({ value, label, color: SEVERITY_BAR_COLORS[value] }))

const LEVEL_FACET: FacetConfig = {
    key: 'level',
    title: 'Level',
    group: 'Standard',
    kind: 'fixed',
    source: { type: 'column', column: 'severity_text', logKey: SEVERITY_LEVEL_FILTER.key },
    fixedOptions: SEVERITY_OPTIONS,
}

const SERVICE_FACET: FacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    kind: 'dynamic',
    source: { type: 'column', column: 'service_name', logKey: SERVICE_NAME_FILTER.key },
    searchable: true,
    searchPlaceholder: 'Search services…',
    emptyLabel: 'No services',
    maxHeight: 300,
}

// Curated OTel resource attributes worth faceting. `key` is the current OTel semantic-convention name;
// `aliasKeys` are older or non-standard spellings of the same attribute that resolveFacets falls back to
// when the tenant doesn't emit the current key.
function resourceAttributeFacet(
    key: string,
    slug: string,
    title: string,
    group: string,
    aliasKeys?: string[]
): FacetConfig {
    return {
        key: slug,
        title,
        group,
        kind: 'dynamic',
        source: { type: 'resourceAttribute', key, aliasKeys },
        searchable: true,
        searchPlaceholder: `Search ${title.toLowerCase()}…`,
        emptyLabel: `No ${title.toLowerCase()} values`,
        maxHeight: 300,
    }
}

// The only faceted attribute semconv has ever renamed: `deployment.environment` became
// `deployment.environment.name` in 1.27. `env` is not a semantic convention — it's what a Datadog `env:`
// tag lands as, since the Datadog ingest path stores ddtags verbatim. The rest below need no aliases:
// the `k8s.*.name` keys are stable and were never renamed, and `host.name` has kept its spelling too.
const ENVIRONMENT_FACET = resourceAttributeFacet(
    'deployment.environment.name',
    'environment',
    'Environment',
    'Standard',
    ['deployment.environment', 'env']
)
const NAMESPACE_FACET = resourceAttributeFacet('k8s.namespace.name', 'namespace', 'Namespace', 'Kubernetes')
const DEPLOYMENT_FACET = resourceAttributeFacet('k8s.deployment.name', 'deployment', 'Deployment', 'Kubernetes')
const POD_FACET = resourceAttributeFacet('k8s.pod.name', 'pod', 'Pod', 'Kubernetes')
const NODE_FACET = resourceAttributeFacet('k8s.node.name', 'node', 'Node', 'Kubernetes')
const HOST_FACET = resourceAttributeFacet('host.name', 'host', 'Host', 'Infrastructure')

/**
 * The rail is rendered entirely from this list — append a config to add a facet (or a new group).
 * Ordered by group (Standard → Kubernetes → Infrastructure) since facetsByGroup keeps first-appearance order.
 * Resource-attribute facets only render when the tenant actually emits the key or one of its aliases
 * (see resolveFacets, called from facetPresenceLogic).
 */
export const FACETS: FacetConfig[] = [
    LEVEL_FACET,
    SERVICE_FACET,
    ENVIRONMENT_FACET,
    NAMESPACE_FACET,
    DEPLOYMENT_FACET,
    POD_FACET,
    NODE_FACET,
    HOST_FACET,
]

/**
 * Resolve the configured facets against the resource-attribute keys a tenant actually emits.
 * Column facets always pass through. A resource-attribute facet is kept only if the tenant emits its
 * current key or one of its aliases, and its source is rewritten onto whichever spelling is present so
 * the rail queries and filters on the key that has data. The current key wins when several are present.
 */
export function resolveFacets(facets: FacetConfig[], presentResourceKeys: string[]): FacetConfig[] {
    const present = new Set(presentResourceKeys)
    const resolved: FacetConfig[] = []
    for (const facet of facets) {
        if (facet.source.type !== 'resourceAttribute') {
            resolved.push(facet)
            continue
        }
        const match = [facet.source.key, ...(facet.source.aliasKeys ?? [])].find((k) => present.has(k))
        if (match === undefined) {
            continue
        }
        resolved.push(match === facet.source.key ? facet : { ...facet, source: { ...facet.source, key: match } })
    }
    return resolved
}

/**
 * Filter facets by a free-text query matching the field name or its group (case-insensitive
 * substring) — powers the rail's "search facets" box. A blank query returns everything, so
 * `facetsByGroup` then drops any group left with no matching facets for free.
 */
export function filterFacetsByName(facets: FacetConfig[], query: string): FacetConfig[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return facets
    }
    return facets.filter(
        (facet) => facet.title.toLowerCase().includes(needle) || facet.group.toLowerCase().includes(needle)
    )
}

/**
 * Ensure every selected (included or excluded) value of a dynamic facet renders even when absent
 * from the fetched list —
 * a filter from a URL or saved view can reference a value with no matches in the current scope
 * (or one below the top-N cutoff), and without a visible row it can't be seen or toggled off.
 * Missing values are prepended with a zero count. An active type-ahead search still applies to
 * injected rows, matching the server-side substring semantics of the fetched ones.
 */
export function mergeSelectedIntoOptions(fetched: FacetOption[], selected: string[], search?: string): FacetOption[] {
    const needle = (search ?? '').trim().toLowerCase()
    const fetchedValues = new Set(fetched.map((option) => option.value))
    // Dedupe: callers pass included+excluded concatenated, and a value hand-edited into both
    // polarities appears in both — without this it would inject a duplicate-keyed row.
    const missing = Array.from(new Set(selected))
        .filter((value) => !fetchedValues.has(value))
        .filter((value) => !needle || value.toLowerCase().includes(needle))
        .map((value) => ({ value, label: value, count: 0 }))
    return missing.length > 0 ? [...missing, ...fetched] : fetched
}

/** Group facets by `group`, preserving first-appearance order of both groups and facets. */
export function facetsByGroup(facets: FacetConfig[]): [string, FacetConfig[]][] {
    const groups: [string, FacetConfig[]][] = []
    for (const facet of facets) {
        const existing = groups.find(([group]) => group === facet.group)
        if (existing) {
            existing[1].push(facet)
        } else {
            groups.push([facet.group, [facet]])
        }
    }
    return groups
}

/** A custom facet's source kind, as persisted per-user — mirrors the backend's `source_type` choices. */
export type CustomFacetSourceType = 'attribute' | 'resourceAttribute'

/** Builds a rail-renderable FacetConfig for a user-added custom facet — always dynamic, with a remove control. */
export function buildCustomFacet(key: string, sourceType: CustomFacetSourceType): FacetConfig {
    return {
        key: `custom:${sourceType}:${key}`,
        title: key,
        group: 'Custom',
        kind: 'dynamic',
        source: sourceType === 'attribute' ? { type: 'attribute', key } : { type: 'resourceAttribute', key },
        searchable: true,
        emptyLabel: `No ${key} values`,
        maxHeight: 300,
        custom: { key, sourceType },
    }
}

/** The (key, sourceType) a custom facet was built from — `null` for a curated facet. */
export function customFacetIdentity(facet: FacetConfig): { key: string; sourceType: CustomFacetSourceType } | null {
    return facet.custom ?? null
}
