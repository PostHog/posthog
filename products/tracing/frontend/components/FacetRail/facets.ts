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
 * - `attribute`: a plain (non-resource) span attribute key, queried with breakdownType `span_attribute`.
 *   Only used by user-added custom facets today — no curated `FACETS` entry uses it.
 */
export type FacetSource =
    | { type: 'column'; column: FacetColumn }
    | { type: 'resourceAttribute'; key: string; aliasKeys?: string[] }
    | { type: 'attribute'; key: string }

/**
 * The sources whose selection lives in the filterGroup. `service_name` is deliberately excluded:
 * its selection belongs in `tracingFiltersLogic.serviceNames` (the field the span queries read) —
 * writing it as a filterGroup property filter would silently not scope the trace list.
 */
export type FilterGroupFacetSource =
    | { type: 'column'; column: Exclude<FacetColumn, 'service_name'> }
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
    /** Required for `fixed` facets: the closed value set with labels. */
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

interface SpanFacetFilter {
    key: string
    type: PropertyFilterType.Span | PropertyFilterType.SpanResourceAttribute | PropertyFilterType.SpanAttribute
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

/** The property filter home for a facet's selection: span filters for status_code, attribute/resource-attribute filters otherwise. */
function facetFilterType(
    source: FacetSource
): PropertyFilterType.Span | PropertyFilterType.SpanResourceAttribute | PropertyFilterType.SpanAttribute {
    switch (source.type) {
        case 'column':
            return PropertyFilterType.Span
        case 'attribute':
            return PropertyFilterType.SpanAttribute
        case 'resourceAttribute':
            return PropertyFilterType.SpanResourceAttribute
    }
}

function facetFilterKey(source: FilterGroupFacetSource): string {
    return source.type === 'column' ? source.column : source.key
}

/**
 * Tri-state selection for a facet: a value is included, excluded, or in neither set. The query
 * effect is `IN (included)` AND `NOT IN (excluded)` — attribute exclusions keep spans missing the
 * attribute entirely (an absent map key reads as '', which never equals an excluded value).
 */
export interface FacetSelection {
    included: string[]
    excluded: string[]
}

// The rail owns a facet's `exact` (include) and `is_not` (exclude) filters. A chip on the same key
// with any other operator (e.g. icontains) is not rail state: it's ignored on read and preserved
// untouched on write.
const RAIL_OPERATORS: PropertyOperator[] = [PropertyOperator.Exact, PropertyOperator.IsNot]

function isRailFacetFilter(filter: SpanFacetFilter, source: FilterGroupFacetSource): boolean {
    return (
        filter?.type === facetFilterType(source) &&
        filter?.key === facetFilterKey(source) &&
        RAIL_OPERATORS.includes(filter?.operator)
    )
}

function filterValues(filter: SpanFacetFilter): string[] {
    const value = filter.value
    if (Array.isArray(value)) {
        // Empty strings from external state (URL, saved view) would select a value with no visible row.
        return value.map(String).filter((v) => v !== '')
    }
    return value != null && value !== '' ? [String(value)] : []
}

/**
 * Selection for a facet whose state lives in the filterGroup (status_code and resource attributes —
 * service_name reads the dedicated serviceNames field instead), read from its exact (include) and
 * is_not (exclude) filters.
 */
export function facetFilterSelection(
    group: UniversalFiltersGroup | undefined,
    source: FilterGroupFacetSource
): FacetSelection {
    const railFilters = innerFilters(group).filter((f) => isRailFacetFilter(f, source))
    return {
        included: railFilters.filter((f) => f.operator === PropertyOperator.Exact).flatMap(filterValues),
        excluded: railFilters.filter((f) => f.operator === PropertyOperator.IsNot).flatMap(filterValues),
    }
}

/**
 * Selection for any facet — routes the service facet to the dedicated serviceNames field
 * (include-only, so nothing is ever excluded there) and everything else to its filterGroup filters.
 * Column selections are reported against the rows the rail renders, so a folded-away value
 * (status_code "0") shows up as its group's row instead of as a selection with no row to click.
 */
export function facetSelection(
    group: UniversalFiltersGroup | undefined,
    serviceNames: string[] | undefined | null,
    source: FacetSource
): FacetSelection {
    if (source.type === 'column') {
        if (source.column === 'service_name') {
            // Empty strings from external state (URL, saved view) would select a value with no visible row.
            return { included: (serviceNames ?? []).filter((v) => v !== ''), excluded: [] }
        }
        return facetRowSelection(source, facetFilterSelection(group, { type: 'column', column: source.column }))
    }
    return facetFilterSelection(group, source)
}

/**
 * Advance `value` one step through the facet cycle — unchecked → included → excluded → unchecked —
 * returning a new filterGroup. Selection is stored as up to two property filters per key with
 * array values, `exact` and `is_not`; a filter is dropped when its side of the selection empties.
 * Both sides are written as whole value groups, so no click can leave half of a folded group behind.
 */
export function cycleFacetFilter(
    group: UniversalFiltersGroup | undefined,
    source: FilterGroupFacetSource,
    value: string
): UniversalFiltersGroup {
    const valueGroup = facetValueGroup(source, value)
    const { included, excluded } = facetFilterSelection(group, source)
    let nextIncluded = included
    let nextExcluded = excluded
    if (valueGroup.some((v) => included.includes(v))) {
        nextIncluded = included.filter((v) => !valueGroup.includes(v))
        nextExcluded = [...excluded, ...valueGroup.filter((v) => !excluded.includes(v))]
    } else if (valueGroup.some((v) => excluded.includes(v))) {
        nextExcluded = excluded.filter((v) => !valueGroup.includes(v))
    } else {
        nextIncluded = [...included, ...valueGroup.filter((v) => !included.includes(v))]
    }

    const values = innerFilters(group).filter((f) => !isRailFacetFilter(f, source))
    const nextIncludedValues = expandToValueGroups(source, nextIncluded)
    const nextExcludedValues = expandToValueGroups(source, nextExcluded)
    if (nextIncludedValues.length > 0) {
        values.push({
            key: facetFilterKey(source),
            type: facetFilterType(source),
            operator: PropertyOperator.Exact,
            value: nextIncludedValues,
        })
    }
    if (nextExcludedValues.length > 0) {
        values.push({
            key: facetFilterKey(source),
            type: facetFilterType(source),
            operator: PropertyOperator.IsNot,
            value: nextExcludedValues,
        })
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

/** The data key a facet is broken down by: its column, or the attribute/resource-attribute key resolution picked. */
export function facetSourceKey(facet: FacetConfig): string {
    return facet.source.type === 'column' ? facet.source.column : facet.source.key
}

/** Everything a facet's own values can depend on, before its own selection is stripped out. */
export interface FacetScope {
    currentTeamId: number | null
    utcDateRange: { date_from?: string | null; date_to?: string | null }
    serviceNames: string[] | undefined
    /** filterGroup with any pinned scope folded in — what the breakdown request actually carries. */
    queryFilterGroup: UniversalFiltersGroup | undefined
}

/**
 * A stable string identifying everything that can change this facet's values: the breakdown scope
 * minus the facet's own contributions, mirroring what the backend strips when excludeBreakdownFilter
 * is set (see _extract_filters in products/tracing/backend/attribute_breakdown_query_runner.py,
 * pinned from the other side by test_attribute_breakdown.py::test_exclude_breakdown_filter_*).
 * Selecting a value in this facet leaves the signature untouched, so the facet doesn't refetch
 * itself; selecting in any other facet changes it.
 *
 * A string, not an object: `queryFilterGroup` gets a fresh identity on every edit, so an object
 * couldn't tell "nothing I care about changed". Presentation state (view mode, sort, compare) is
 * deliberately absent — the breakdown request doesn't read it.
 */
export function facetScopeSignature(facet: FacetConfig, scope: FacetScope): string {
    const { source } = facet
    const selfKey = facetSourceKey(facet)
    const selfType = facetFilterType(source)
    // Any operator: the backend drops every filter under the breakdown key, not just the rail's own.
    const groupSignature = innerFilters(scope.queryFilterGroup)
        .filter((filter) => !(filter.type === selfType && filter.key === selfKey))
        .map((filter) => [filter.type, filter.key, filter.operator, JSON.stringify(filter.value ?? null)])

    return JSON.stringify([
        // A facet mounted before the team resolved fetches nothing; keeping the id in the signature
        // makes it fetch once the team arrives.
        scope.currentTeamId ?? null,
        [source.type, selfKey],
        scope.utcDateRange.date_from ?? null,
        scope.utcDateRange.date_to ?? null,
        // The service facet breaks down the same column the dedicated field filters.
        source.type === 'column' && source.column === 'service_name' ? null : (scope.serviceNames ?? []),
        groupSignature,
    ])
}

// A span that never had its status explicitly set carries no distinct meaning from one marked
// OK, so the rail folds status_code 0 (Unset) into the OK row: selecting, excluding, and counting
// "1" also reads and writes "0". Keyed on the digit strings the breakdown rows and filter values
// already use.
const STATUS_CODE_VALUE_GROUPS: Record<string, string[]> = {
    '1': ['0', '1'],
}

/**
 * The full set of underlying column values a facet click or count should read/write for `value`.
 * Only status_code's "OK" (folding in "Unset") expands to more than itself; every other facet
 * value, including status_code's "Error", is its own singleton group.
 */
export function facetValueGroup(source: FacetSource, value: string): string[] {
    if (source.type === 'column' && source.column === 'status_code') {
        return STATUS_CODE_VALUE_GROUPS[value] ?? [value]
    }
    return [value]
}

// Reverse of STATUS_CODE_VALUE_GROUPS: which row each underlying value is rendered under.
const STATUS_CODE_ROW_BY_VALUE: Record<string, string> = Object.fromEntries(
    Object.entries(STATUS_CODE_VALUE_GROUPS).flatMap(([row, values]) => values.map((value) => [value, row]))
)

/**
 * The rail row `value` is rendered under: itself for every value except one that was folded away,
 * which reports the row it folded into. Filters written before the fold (or by hand outside the
 * rail) can carry status_code "0" on its own, so the OK row has to read as active for it; otherwise
 * the first click would cycle that already-active group to excluded instead of selecting it.
 */
function facetRowValue(source: FacetSource, value: string): string {
    if (source.type === 'column' && source.column === 'status_code') {
        return STATUS_CODE_ROW_BY_VALUE[value] ?? value
    }
    return value
}

/** Map a raw filter selection onto the rows the rail renders, deduping values that share a row. */
function facetRowSelection(source: FacetSource, selection: FacetSelection): FacetSelection {
    const toRows = (values: string[]): string[] => [...new Set(values.map((v) => facetRowValue(source, v)))]
    return { included: toRows(selection.included), excluded: toRows(selection.excluded) }
}

/**
 * Expand a set of filter values onto whole value groups, so a write always covers every value behind
 * the rows it touches. Legacy state carrying part of a group (status_code "0" without "1") would
 * otherwise survive a click on a different row, leaving the rail showing OK while the query drops
 * explicitly-OK spans.
 */
function expandToValueGroups(source: FacetSource, values: string[]): string[] {
    return [...new Set(values.flatMap((v) => facetValueGroup(source, facetRowValue(source, v))))]
}

// OTel span status. Values must stay the digit strings "1"/"2": breakdown rows arrive
// stringified (the backend toString()s the Int16 column), so these are what counts key on.
// "Unset" (0) has no separate row; see STATUS_CODE_VALUE_GROUPS above.
const STATUS_OPTIONS: FacetOption[] = [
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
    maxHeight: 300,
}

const STATUS_FACET: FacetConfig = {
    key: 'status',
    title: 'Status',
    group: 'Standard',
    kind: 'fixed',
    source: { type: 'column', column: 'status_code' },
    fixedOptions: STATUS_OPTIONS,
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
// the `k8s.*.name` keys and `service.version` are stable and were never renamed, and `host.name` has
// kept its spelling too.
const ENVIRONMENT_FACET = resourceAttributeFacet(
    'deployment.environment.name',
    'environment',
    'Environment',
    'Standard',
    ['deployment.environment', 'env']
)
const VERSION_FACET = resourceAttributeFacet('service.version', 'version', 'Version', 'Standard')
const NAMESPACE_FACET = resourceAttributeFacet('k8s.namespace.name', 'namespace', 'Namespace', 'Kubernetes')
const DEPLOYMENT_FACET = resourceAttributeFacet('k8s.deployment.name', 'deployment', 'Deployment', 'Kubernetes')
const HOST_FACET = resourceAttributeFacet('host.name', 'host', 'Host', 'Infrastructure')

/**
 * The rail is rendered entirely from this list — append a config to add a facet (or a new group).
 * Ordered by group (Standard → Kubernetes → Infrastructure) since facetsByGroup keeps first-appearance order.
 * Resource-attribute facets only render when the tenant actually emits the key or one of its aliases
 * (see resolveFacets, called from facetCountsLogic).
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
 * Ensure every selected value of a dynamic facet renders even when absent from the fetched list —
 * a filter from a URL or saved view can reference a value with no matches in the current scope
 * (or one below the top-N cutoff), and without a visible row it can't be seen or toggled off.
 * Missing values are prepended with a zero count. An active type-ahead search still applies to
 * injected rows, matching the server-side substring semantics of the fetched ones.
 */
export function mergeSelectedIntoOptions(fetched: FacetOption[], selected: string[], search?: string): FacetOption[] {
    const needle = (search ?? '').trim().toLowerCase()
    const seen = new Set(fetched.map((option) => option.value))
    // Dedupe as we go: a URL or saved view can carry the same value twice, and two rows sharing a
    // value would collide on their React key and toggle target.
    const missing: FacetOption[] = []
    for (const value of selected) {
        if (seen.has(value) || (needle && !value.toLowerCase().includes(needle))) {
            continue
        }
        seen.add(value)
        missing.push({ value, label: value, count: 0 })
    }
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
