import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { SEVERITY_BAR_COLORS } from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'

import { FieldOption } from './Field'

/**
 * Whether a field's value set is known ahead of time or discovered from the data.
 *
 * - `fixed`: a closed enum defined here in code (e.g. severity levels). The full list is rendered
 *   regardless of the data; values with a zero count show dimmed rather than disappearing.
 * - `dynamic`: values come back from the data at query time (e.g. service names) and change with
 *   the active filters. Only values present in the current scope appear — zeros never show.
 */
export type FieldKind = 'fixed' | 'dynamic'

/** The `logsViewerFiltersLogic` field a column field's selection is written to. */
export type FieldFilterKey = 'severityLevels' | 'serviceNames'

/** The ClickHouse column a column field's values + counts are computed over (matches backend FIELD_COLUMNS). */
export type LogColumn = 'severity_text' | 'service_name'

/**
 * Where a field's field lives, which determines both how it's queried and how its selection is stored.
 *
 * - `column`: a top-level logs column. Selection lives in a dedicated filter field (severityLevels/serviceNames).
 * - `resourceAttribute`: a `resource_attributes` map key (e.g. k8s.namespace.name). No dedicated field —
 *   selection is stored as a `log_resource_attribute` property filter inside the filterGroup.
 */
export type FieldSource =
    | { type: 'column'; column: LogColumn; filterKey: FieldFilterKey }
    | { type: 'resourceAttribute'; key: string }

export interface FieldConfig {
    /** Stable id used for collapse state and data-attrs. */
    key: string
    /** User-facing field name shown as the field header. */
    title: string
    /** Header the field is grouped under in the rail (e.g. "Standard"). */
    group: string
    kind: FieldKind
    source: FieldSource
    /** Required for `fixed` fields: the closed value set, with labels + colors. */
    fixedOptions?: FieldOption[]
    /** Renders a search box and virtualizes the list — for `dynamic` fields with many values. */
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

/** Values currently selected for a resource-attribute field, read from the log_resource_attribute filter. */
export function resourceAttributeValues(group: UniversalFiltersGroup | undefined, key: string): string[] {
    const existing = innerFilters(group).find((f) => isResourceAttributeFilter(f, key))
    const value = existing?.value
    if (Array.isArray(value)) {
        return value as string[]
    }
    return value != null && value !== '' ? [String(value)] : []
}

/**
 * Add or remove `value` from a resource-attribute field's selection, returning a new filterGroup.
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
const SEVERITY_OPTIONS: FieldOption[] = (
    [
        ['trace', 'Trace'],
        ['debug', 'Debug'],
        ['info', 'Info'],
        ['warn', 'Warn'],
        ['error', 'Error'],
        ['fatal', 'Fatal'],
    ] as const
).map(([value, label]) => ({ value, label, color: SEVERITY_BAR_COLORS[value] }))

const LEVEL_FIELD: FieldConfig = {
    key: 'level',
    title: 'Level',
    group: 'Standard',
    kind: 'fixed',
    source: { type: 'column', column: 'severity_text', filterKey: 'severityLevels' },
    fixedOptions: SEVERITY_OPTIONS,
}

const SERVICE_FIELD: FieldConfig = {
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

// Curated OTel resource attributes worth surfacing as fields. Keys are the stable OTel semantic-convention names;
// `deployment.environment.name` is the 1.27+ stable key (older data may use `deployment.environment`).
function resourceAttributeField(key: string, slug: string, title: string, group: string): FieldConfig {
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

const ENVIRONMENT_FIELD = resourceAttributeField(
    'deployment.environment.name',
    'environment',
    'Environment',
    'Standard'
)
const NAMESPACE_FIELD = resourceAttributeField('k8s.namespace.name', 'namespace', 'Namespace', 'Kubernetes')
const DEPLOYMENT_FIELD = resourceAttributeField('k8s.deployment.name', 'deployment', 'Deployment', 'Kubernetes')
const POD_FIELD = resourceAttributeField('k8s.pod.name', 'pod', 'Pod', 'Kubernetes')
const NODE_FIELD = resourceAttributeField('k8s.node.name', 'node', 'Node', 'Kubernetes')
const HOST_FIELD = resourceAttributeField('host.name', 'host', 'Host', 'Infrastructure')

/**
 * The rail is rendered entirely from this list — append a config to add a field (or a new group).
 * Ordered by group (Standard → Kubernetes → Infrastructure) since fieldsByGroup keeps first-appearance order.
 * Resource-attribute fields only render when the tenant actually emits the key (see fieldCountsLogic).
 */
export const FIELDS: FieldConfig[] = [
    LEVEL_FIELD,
    SERVICE_FIELD,
    ENVIRONMENT_FIELD,
    NAMESPACE_FIELD,
    DEPLOYMENT_FIELD,
    POD_FIELD,
    NODE_FIELD,
    HOST_FIELD,
]

/** Group fields by `group`, preserving first-appearance order of both groups and fields. */
export function fieldsByGroup(fields: FieldConfig[]): [string, FieldConfig[]][] {
    const groups: [string, FieldConfig[]][] = []
    for (const field of fields) {
        const existing = groups.find(([group]) => group === field.group)
        if (existing) {
            existing[1].push(field)
        } else {
            groups.push([field.group, [field]])
        }
    }
    return groups
}
