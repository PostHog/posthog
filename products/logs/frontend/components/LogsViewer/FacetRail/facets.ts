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
 *   selection is stored as up to two `log_resource_attribute` property filters inside the filterGroup:
 *   `exact` for included values and `is_not` for excluded ones.
 */
export type FacetSource =
    | {
          type: 'column'
          column: FacetField
          filterKey: FacetFilterKey
          /**
           * The `log` property-filter key the facet's exclusions are stored under (e.g. severity_level).
           * Includes stay in the dedicated field; without this, the facet is two-state (no exclusions).
           */
          exclusionKey?: string
      }
    | { type: 'resourceAttribute'; key: string; aliasKeys?: string[] }

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

interface RailPropertyFilter {
    key: string
    type: PropertyFilterType.Log | PropertyFilterType.LogResourceAttribute
    operator: PropertyOperator
    value?: PropertyFilterValue
}

// The inner group holds property filters, but can also hold a nested group — one value ORed across
// several attribute keys (e.g. the person-scope distinct-id group).
type RailFilterEntry = RailPropertyFilter | UniversalFiltersGroup

// The logs filterGroup is always { AND, values: [{ AND, values: [<property filters>] }] } — the
// editable property filters live in the single inner group.
function innerFilters(group: UniversalFiltersGroup | undefined): RailFilterEntry[] {
    return ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ?? []) as RailFilterEntry[]
}

function isPropertyLeaf(entry: RailFilterEntry): entry is RailPropertyFilter {
    return !('values' in entry)
}

/**
 * Tri-state selection for a facet: a value is included, excluded, or in neither set. The query
 * effect is `IN (included)` AND `NOT IN (excluded)` — attribute exclusions keep rows missing the
 * attribute entirely.
 */
export interface FacetSelection {
    included: string[]
    excluded: string[]
}

// The rail owns a key's `exact` (include) and `is_not` (exclude) filters. A chip on the same key
// with any other operator (e.g. icontains) is not rail state: it's ignored on read and preserved
// untouched on write.
const RAIL_OPERATORS: PropertyOperator[] = [PropertyOperator.Exact, PropertyOperator.IsNot]

function isRailFacetFilter(entry: RailFilterEntry, key: string): entry is RailPropertyFilter {
    return (
        isPropertyLeaf(entry) &&
        entry?.type === PropertyFilterType.LogResourceAttribute &&
        entry?.key === key &&
        RAIL_OPERATORS.includes(entry?.operator)
    )
}

function filterValues(filter: RailPropertyFilter): string[] {
    const value = filter.value
    if (Array.isArray(value)) {
        return value as string[]
    }
    return value != null && value !== '' ? [String(value)] : []
}

/** A resource-attribute facet's selection, read from its exact (include) and is_not (exclude) filters. */
export function resourceAttributeSelection(group: UniversalFiltersGroup | undefined, key: string): FacetSelection {
    const railFilters = innerFilters(group).filter((f) => isRailFacetFilter(f, key))
    return {
        included: railFilters.filter((f) => f.operator === PropertyOperator.Exact).flatMap(filterValues),
        excluded: railFilters.filter((f) => f.operator === PropertyOperator.IsNot).flatMap(filterValues),
    }
}

/**
 * Advance `value` one step through the facet cycle — unchecked → included → excluded → unchecked —
 * returning a new filterGroup. Selection is stored as up to two log_resource_attribute filters per
 * key with array values, `exact` and `is_not` (logs have no `in` operator); a filter is dropped
 * when its side of the selection empties.
 */
export function cycleResourceAttributeFilter(
    group: UniversalFiltersGroup | undefined,
    key: string,
    value: string
): UniversalFiltersGroup {
    const { included, excluded } = resourceAttributeSelection(group, key)
    let nextIncluded = included
    let nextExcluded = excluded
    if (included.includes(value)) {
        nextIncluded = included.filter((v) => v !== value)
        nextExcluded = excluded.includes(value) ? excluded : [...excluded, value]
    } else if (excluded.includes(value)) {
        nextExcluded = excluded.filter((v) => v !== value)
    } else {
        nextIncluded = [...included, value]
    }

    // Annotated: negating the type guard would otherwise narrow the survivors to nested groups.
    const values: RailFilterEntry[] = innerFilters(group).filter((f) => !isRailFacetFilter(f, key))
    if (nextIncluded.length > 0) {
        values.push({
            key,
            type: PropertyFilterType.LogResourceAttribute,
            operator: PropertyOperator.Exact,
            value: nextIncluded,
        })
    }
    if (nextExcluded.length > 0) {
        values.push({
            key,
            type: PropertyFilterType.LogResourceAttribute,
            operator: PropertyOperator.IsNot,
            value: nextExcluded,
        })
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

// A column facet's exclusions are the `is_not` `log` property filter under the facet's
// exclusionKey. The rail owns only that filter — includes live in the facet's dedicated query
// field, so an `exact` chip on the same key is chips-bar state: ignored on read, preserved on write.
function isLogExclusionFilter(entry: RailFilterEntry, key: string): entry is RailPropertyFilter {
    return (
        isPropertyLeaf(entry) &&
        entry?.type === PropertyFilterType.Log &&
        entry?.key === key &&
        entry?.operator === PropertyOperator.IsNot
    )
}

/** A column facet's excluded values, read from the `is_not` log filter under `key`. */
export function logFilterExclusions(group: UniversalFiltersGroup | undefined, key: string): string[] {
    return innerFilters(group)
        .filter((f) => isLogExclusionFilter(f, key))
        .flatMap(filterValues)
}

/** Replace the `is_not` log filter under `key` with `excluded`, dropping the filter when empty. */
export function setLogFilterExclusions(
    group: UniversalFiltersGroup | undefined,
    key: string,
    excluded: string[]
): UniversalFiltersGroup {
    // Annotated: negating the type guard would otherwise narrow the survivors to nested groups.
    const values: RailFilterEntry[] = innerFilters(group).filter((f) => !isLogExclusionFilter(f, key))
    if (excluded.length > 0) {
        values.push({ key, type: PropertyFilterType.Log, operator: PropertyOperator.IsNot, value: excluded })
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

// The `log` property-filter key the backend drops alongside a column facet's dedicated field, keyed
// by column rather than by FacetConfig.exclusionKey: the backend strips by column whatever the rail
// happens to write. Mirrors LogsFilterBuilder.where() in products/logs/backend/logs_query_runner.py,
// pinned from the other side by products/logs/backend/test/test_log_facet_values.py.
const COLUMN_SELF_LOG_KEY: Record<FacetField, string> = {
    severity_text: 'severity_level',
    service_name: 'service_name',
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
    severityLevels?: string[] | null
    serviceNames?: string[] | null
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
    const selfLogKey = source.type === 'column' ? COLUMN_SELF_LOG_KEY[source.column] : undefined
    const selfResourceKey = source.type === 'resourceAttribute' ? source.key : undefined
    const groupSignature = innerFilters(scope.queryFilterGroup)
        .map((entry): unknown[] | null => {
            if (!isPropertyLeaf(entry)) {
                // Nested groups aren't leaves the backend can strip — carry them whole.
                return ['group', JSON.stringify(entry)]
            }
            // Any operator: the backend skips a log filter under the facet's own column wholesale.
            if (selfLogKey !== undefined && entry.type === PropertyFilterType.Log && entry.key === selfLogKey) {
                return null
            }
            // Both polarities, any operator.
            if (
                selfResourceKey !== undefined &&
                entry.type === PropertyFilterType.LogResourceAttribute &&
                entry.key === selfResourceKey
            ) {
                return null
            }
            return [entry.type, entry.key, entry.operator, JSON.stringify(entry.value ?? null)]
        })
        .filter((entry) => entry !== null)

    return JSON.stringify([
        // A facet mounted before the team resolved fetches nothing; keeping the id in the signature
        // makes it fetch once the team arrives.
        scope.currentTeamId ?? null,
        source.type === 'column' ? ['column', source.column] : ['resource', source.key],
        scope.utcDateRange.date_from ?? null,
        scope.utcDateRange.date_to ?? null,
        scope.utcDateRange.explicitDate ?? null,
        scope.searchTerm || null,
        source.type === 'column' && source.column === 'severity_text' ? null : (scope.severityLevels ?? []),
        source.type === 'column' && source.column === 'service_name' ? null : (scope.serviceNames ?? []),
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
    source: { type: 'column', column: 'severity_text', filterKey: 'severityLevels', exclusionKey: 'severity_level' },
    fixedOptions: SEVERITY_OPTIONS,
}

const SERVICE_FACET: FacetConfig = {
    key: 'service',
    title: 'Service',
    group: 'Standard',
    kind: 'dynamic',
    source: { type: 'column', column: 'service_name', filterKey: 'serviceNames', exclusionKey: 'service_name' },
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
        if (facet.source.type === 'column') {
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
