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

/** The `logsViewerFiltersLogic` field a facet's selection is written to. */
export type FacetFilterKey = 'severityLevels' | 'serviceNames'

/** The ClickHouse column a facet's values + counts are computed over (matches the backend FACET_FIELDS). */
export type FacetField = 'severity_text' | 'service_name'

export interface FacetConfig {
    /** Stable id used for collapse state and data-attrs. */
    key: string
    /** User-facing field name shown as the facet header. */
    title: string
    /** Header the facet is grouped under in the rail (e.g. "Standard"). */
    group: string
    kind: FacetKind
    filterKey: FacetFilterKey
    facetField: FacetField
    /** Required for `fixed` facets: the closed value set, with labels + colors. */
    fixedOptions?: FacetOption[]
    /** Renders a search box and virtualizes the list — for `dynamic` facets with many values. */
    searchable?: boolean
    searchPlaceholder?: string
    emptyLabel?: string
    /** Max pixel height before the value list virtualizes and scrolls. */
    maxHeight?: number
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
    filterKey: 'severityLevels',
    facetField: 'severity_text',
    fixedOptions: SEVERITY_OPTIONS,
}

const SERVICE_FACET: FacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    kind: 'dynamic',
    filterKey: 'serviceNames',
    facetField: 'service_name',
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
