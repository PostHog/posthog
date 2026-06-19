import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

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
    type: PropertyFilterType
    operator: PropertyOperator
    value?: unknown
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
    const values =
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

/** The rail is rendered entirely from this list — append a config to add a facet (or a new group). */
export const FACETS: FacetConfig[] = [LEVEL_FACET, SERVICE_FACET]

/** `FACETS` grouped by `group`, preserving first-appearance order of both groups and facets. */
export function facetsByGroup(): [string, FacetConfig[]][] {
    const groups: [string, FacetConfig[]][] = []
    for (const facet of FACETS) {
        const existing = groups.find(([group]) => group === facet.group)
        if (existing) {
            existing[1].push(facet)
        } else {
            groups.push([facet.group, [facet]])
        }
    }
    return groups
}
