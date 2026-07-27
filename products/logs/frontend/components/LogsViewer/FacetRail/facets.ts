import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { SEVERITY_BAR_COLORS } from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'

import { FacetOption } from './Facet'

/**
 * Whether a facet's value set is known ahead of time or discovered from the data.
 *
 * - `fixed`: a closed enum defined here in code (e.g. severity levels). The full list is rendered
 *   regardless of the data; values with a zero count show dimmed rather than disappearing.
 * - `dynamic`: values come back from the data at query time (e.g. service names) and change with
 *   the active filters. Only values present in the current scope appear — zeros never show.
 */
export type FacetKind = 'fixed' | 'dynamic'

/** The `logsViewerFiltersLogic` field a column facet's selection is written to. */
export type FacetFilterKey = 'severityLevels' | 'serviceNames'

/** The ClickHouse column a column facet's values + counts are computed over (matches backend FACET_FIELDS). */
export type FacetField = 'severity_text' | 'service_name'

/**
 * Where a facet's field lives, which determines both how it's queried and how its selection is stored.
 *
 * - `column`: a top-level logs column. Selection lives in a dedicated filter field (severityLevels/serviceNames).
 * - `resourceAttribute`: a `resource_attributes` map key (e.g. k8s.namespace.name). No dedicated field —
 *   selection is stored as a `log_resource_attribute` property filter inside the filterGroup.
 */
export type FacetSource =
    | { type: 'column'; column: FacetField; filterKey: FacetFilterKey }
    | { type: 'resourceAttribute'; key: string }

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
}

interface LogResourceAttributeFilter {
    key: string
    type: PropertyFilterType.LogResourceAttribute
    operator: PropertyOperator
    value?: PropertyFilterValue
}

// The logs filterGroup is always { AND, values: [{ AND, values: [<property filters>] }] } — the
// editable property filters live in the single inner group.
function innerFilters(group: UniversalFiltersGroup | undefined): LogResourceAttributeFilter[] {
    return ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ?? []) as LogResourceAttributeFilter[]
}

function isResourceAttributeFilter(filter: LogResourceAttributeFilter, key: string): boolean {
    return filter?.type === PropertyFilterType.LogResourceAttribute && filter?.key === key
}

/** Values currently selected for a resource-attribute facet, read from the log_resource_attribute filter. */
export function resourceAttributeValues(group: UniversalFiltersGroup | undefined, key: string): string[] {
    const existing = innerFilters(group).find((f) => isResourceAttributeFilter(f, key))
    const value = existing?.value
    if (Array.isArray(value)) {
        return value as string[]
    }
    return value != null && value !== '' ? [String(value)] : []
}

/**
 * Add or remove `value` from a resource-attribute facet's selection, returning a new filterGroup.
 * Multi-select is one log_resource_attribute filter per key with an array value (logs have no `in` operator).
 */
export function toggleResourceAttributeFilter(
    group: UniversalFiltersGroup | undefined,
    key: string,
    value: string
): UniversalFiltersGroup {
    const current = resourceAttributeValues(group, key)
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    const others = innerFilters(group).filter((f) => !isResourceAttributeFilter(f, key))
    const values: LogResourceAttributeFilter[] =
        next.length > 0
            ? [
                  ...others,
                  { key, type: PropertyFilterType.LogResourceAttribute, operator: PropertyOperator.Exact, value: next },
              ]
            : others
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
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
    source: { type: 'column', column: 'severity_text', filterKey: 'severityLevels' },
    fixedOptions: SEVERITY_OPTIONS,
}

const SERVICE_FACET: FacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    kind: 'dynamic',
    source: { type: 'column', column: 'service_name', filterKey: 'serviceNames' },
    searchable: true,
    searchPlaceholder: 'Search services…',
    emptyLabel: 'No services',
    maxHeight: 300,
}

// Curated OTel resource attributes worth faceting. Keys are the stable OTel semantic-convention names;
// `deployment.environment.name` is the 1.27+ stable key (older data may use `deployment.environment`).
function resourceAttributeFacet(key: string, slug: string, title: string, group: string): FacetConfig {
    return {
        key: slug,
        title,
        group,
        kind: 'dynamic',
        source: { type: 'resourceAttribute', key },
        searchable: true,
        searchPlaceholder: `Search ${title.toLowerCase()}…`,
        emptyLabel: `No ${title.toLowerCase()} values`,
        maxHeight: 300,
    }
}

const ENVIRONMENT_FACET = resourceAttributeFacet(
    'deployment.environment.name',
    'environment',
    'Environment',
    'Standard'
)
const NAMESPACE_FACET = resourceAttributeFacet('k8s.namespace.name', 'namespace', 'Namespace', 'Kubernetes')
const DEPLOYMENT_FACET = resourceAttributeFacet('k8s.deployment.name', 'deployment', 'Deployment', 'Kubernetes')
const POD_FACET = resourceAttributeFacet('k8s.pod.name', 'pod', 'Pod', 'Kubernetes')
const NODE_FACET = resourceAttributeFacet('k8s.node.name', 'node', 'Node', 'Kubernetes')
const HOST_FACET = resourceAttributeFacet('host.name', 'host', 'Host', 'Infrastructure')

/**
 * The rail is rendered entirely from this list — append a config to add a facet (or a new group).
 * Ordered by group (Standard → Kubernetes → Infrastructure) since facetsByGroup keeps first-appearance order.
 * Resource-attribute facets only render when the tenant actually emits the key (see facetCountsLogic).
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
 * Ensure every selected value of a dynamic facet renders even when absent from the fetched list —
 * a filter from a URL or saved view can reference a value with no matches in the current scope
 * (or one below the top-N cutoff), and without a visible row it can't be seen or toggled off.
 * Missing values are prepended with a zero count. An active type-ahead search still applies to
 * injected rows, matching the server-side substring semantics of the fetched ones.
 */
export function mergeSelectedIntoOptions(fetched: FacetOption[], selected: string[], search?: string): FacetOption[] {
    const needle = (search ?? '').trim().toLowerCase()
    const fetchedValues = new Set(fetched.map((option) => option.value))
    const missing = selected
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
