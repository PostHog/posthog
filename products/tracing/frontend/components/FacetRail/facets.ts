import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

/** One selectable row in a facet: a value with its span count. */
export interface FacetOption {
    value: string
    label: string
    count: number
}

/**
 * Whether a facet's value set is known ahead of time or discovered from the data.
 *
 * - `fixed`: a closed enum defined here in code (e.g. span status). The full list is rendered
 *   regardless of the data; values with a zero count show dimmed rather than disappearing.
 * - `dynamic`: values come back from the data at query time (e.g. service names) and change with
 *   the active filters. Only values present in the current scope appear — zeros never show.
 */
export type FacetKind = 'fixed' | 'dynamic'

/** Top-level trace_spans columns a facet may group by (matches backend FACET_COLUMNS). */
export type FacetColumn = 'service_name' | 'status_code'

/**
 * Where a facet's field lives, which determines both how it's queried and how its selection is stored.
 *
 * - `column`: an allowlisted top-level span column, queried with breakdownType `span`. `service_name`'s
 *   selection lives in the dedicated `serviceNames` filter field; `status_code`'s in a span property filter.
 * - `resourceAttribute`: a `resource_attributes` map key (e.g. k8s.namespace.name), queried with
 *   breakdownType `span_resource_attribute`. Selection is a span_resource_attribute property filter.
 */
export type FacetSource = { type: 'column'; column: FacetColumn } | { type: 'resourceAttribute'; key: string }

/**
 * The sources whose selection lives in the filterGroup. `service_name` is deliberately excluded:
 * its selection belongs in `tracingFiltersLogic.serviceNames` (the field the span queries read) —
 * writing it as a filterGroup property filter would silently not scope the trace list.
 */
export type FilterGroupFacetSource =
    | { type: 'column'; column: Exclude<FacetColumn, 'service_name'> }
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
    /** Required for `fixed` facets: the closed value set with labels. */
    fixedOptions?: FacetOption[]
    /** Renders a search box and virtualizes the list — for `dynamic` facets with many values. */
    searchable?: boolean
    searchPlaceholder?: string
    emptyLabel?: string
}

interface SpanFacetFilter {
    key: string
    type: PropertyFilterType.Span | PropertyFilterType.SpanResourceAttribute
    operator: PropertyOperator
    value?: PropertyFilterValue
}

/**
 * The editable property filters of a tracing filterGroup, which is always
 * { AND, values: [{ AND, values: [<property filters>] }] } — the filters live in the single inner group.
 */
export function innerFilters(group: UniversalFiltersGroup | undefined): SpanFacetFilter[] {
    return ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ?? []) as SpanFacetFilter[]
}

/** The property filter home for a facet's selection: span filters for status_code, resource-attribute filters otherwise. */
function facetFilterType(
    source: FilterGroupFacetSource
): PropertyFilterType.Span | PropertyFilterType.SpanResourceAttribute {
    return source.type === 'column' ? PropertyFilterType.Span : PropertyFilterType.SpanResourceAttribute
}

function facetFilterKey(source: FilterGroupFacetSource): string {
    return source.type === 'column' ? source.column : source.key
}

function isFacetFilter(filter: SpanFacetFilter, source: FilterGroupFacetSource): boolean {
    return filter?.type === facetFilterType(source) && filter?.key === facetFilterKey(source)
}

/**
 * Values currently selected for a facet whose selection lives in the filterGroup (status_code and
 * resource attributes — service_name reads the dedicated serviceNames field instead).
 */
export function facetFilterValues(group: UniversalFiltersGroup | undefined, source: FilterGroupFacetSource): string[] {
    const existing = innerFilters(group).find((f) => isFacetFilter(f, source))
    const value = existing?.value
    if (Array.isArray(value)) {
        return value.map(String)
    }
    return value != null && value !== '' ? [String(value)] : []
}

/**
 * Add or remove `value` from a facet's filterGroup selection, returning a new filterGroup.
 * Multi-select is one property filter per key with an array value.
 */
export function toggleFacetFilter(
    group: UniversalFiltersGroup | undefined,
    source: FilterGroupFacetSource,
    value: string
): UniversalFiltersGroup {
    const current = facetFilterValues(group, source)
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    const others = innerFilters(group).filter((f) => !isFacetFilter(f, source))
    const values: SpanFacetFilter[] =
        next.length > 0
            ? [
                  ...others,
                  {
                      key: facetFilterKey(source),
                      type: facetFilterType(source),
                      operator: PropertyOperator.Exact,
                      value: next,
                  },
              ]
            : others
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

// OTel span status. Values must stay the digit strings "0"/"1"/"2": breakdown rows arrive
// stringified (the backend toString()s the Int16 column), so these are what counts key on.
// Don't switch to the label strings — the server-side filter normaliser treats "OK" as
// {Unset, OK}, which would silently widen a selection.
const STATUS_OPTIONS: FacetOption[] = [
    { value: '0', label: 'Unset', count: 0 },
    { value: '1', label: 'OK', count: 0 },
    { value: '2', label: 'Error', count: 0 },
]

const SERVICE_FACET: FacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    kind: 'dynamic',
    source: { type: 'column', column: 'service_name' },
    searchable: true,
    searchPlaceholder: 'Search services…',
    emptyLabel: 'No services',
}

const STATUS_FACET: FacetConfig = {
    key: 'status',
    title: 'Status',
    group: 'Standard',
    kind: 'fixed',
    source: { type: 'column', column: 'status_code' },
    fixedOptions: STATUS_OPTIONS,
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
    }
}

const ENVIRONMENT_FACET = resourceAttributeFacet(
    'deployment.environment.name',
    'environment',
    'Environment',
    'Standard'
)
const VERSION_FACET = resourceAttributeFacet('service.version', 'version', 'Version', 'Standard')
const NAMESPACE_FACET = resourceAttributeFacet('k8s.namespace.name', 'namespace', 'Namespace', 'Kubernetes')
const DEPLOYMENT_FACET = resourceAttributeFacet('k8s.deployment.name', 'deployment', 'Deployment', 'Kubernetes')
const HOST_FACET = resourceAttributeFacet('host.name', 'host', 'Host', 'Infrastructure')

/**
 * The rail is rendered entirely from this list — append a config to add a facet (or a new group).
 * Ordered by group (Standard → Kubernetes → Infrastructure) since facetsByGroup keeps first-appearance order.
 * Resource-attribute facets only render when the tenant actually emits the key (see facetCountsLogic).
 */
export const FACETS: FacetConfig[] = [
    SERVICE_FACET,
    STATUS_FACET,
    ENVIRONMENT_FACET,
    VERSION_FACET,
    NAMESPACE_FACET,
    DEPLOYMENT_FACET,
    HOST_FACET,
]

// List-shaping helpers for rendering the rail (grouping, name search, merging selected values
// into fetched options) land with their consumer, the Facet/FacetRail components.
