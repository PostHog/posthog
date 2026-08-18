/**
 * How a facet's tri-state selection is stored in the logs filterGroup: one property filter per
 * polarity under the facet's own key, `exact` for included values and `is_not` for excluded ones.
 *
 * This is the only store for a facet selection, which is what keeps the rail's checkboxes and the
 * chips bar in agreement: both read these filters, and every rail click rewrites them.
 */

import {
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import type { FacetSource } from './facets'

/** The property-filter type a facet's selection is stored as, per source kind. */
export type FacetFilterType = PropertyFilterType.Log | PropertyFilterType.LogResourceAttribute

/** The property filter a facet owns inside the filterGroup: one type + key pair, both polarities. */
export interface FacetFilterTarget {
    key: string
    type: FacetFilterType
}

interface RailPropertyFilter {
    key: string
    type: FacetFilterType
    operator: PropertyOperator
    value?: PropertyFilterValue
}

// The inner group holds property filters, but can also hold a nested group — one value ORed across
// several attribute keys (e.g. the person-scope distinct-id group).
type RailFilterEntry = RailPropertyFilter | UniversalFiltersGroup

// The logs filterGroup is always { AND, values: [{ AND, values: [<property filters>] }] } — the
// editable property filters live in the single inner group. Exported for facetScopeSignature, which
// walks the same entries to decide what a facet's values depend on.
export function innerFilters(group: UniversalFiltersGroup | undefined): RailFilterEntry[] {
    return ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ?? []) as RailFilterEntry[]
}

export function isPropertyLeaf(entry: RailFilterEntry): entry is RailPropertyFilter {
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

function isRailFacetFilter(entry: RailFilterEntry, target: FacetFilterTarget): entry is RailPropertyFilter {
    return (
        isPropertyLeaf(entry) &&
        entry?.type === target.type &&
        entry?.key === target.key &&
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

/** The filterGroup property filter a facet's selection is stored in, derived from its source. */
export function facetFilterTarget(source: FacetSource): FacetFilterTarget {
    return source.type === 'column'
        ? { key: source.logKey, type: PropertyFilterType.Log }
        : { key: source.key, type: PropertyFilterType.LogResourceAttribute }
}

/** A facet's selection, read from the exact (include) and is_not (exclude) filters it owns. */
export function facetSelection(group: UniversalFiltersGroup | undefined, target: FacetFilterTarget): FacetSelection {
    const railFilters = innerFilters(group).filter((f) => isRailFacetFilter(f, target))
    return {
        included: railFilters.filter((f) => f.operator === PropertyOperator.Exact).flatMap(filterValues),
        excluded: railFilters.filter((f) => f.operator === PropertyOperator.IsNot).flatMap(filterValues),
    }
}

/**
 * Replace a facet's selection, returning a new filterGroup. Both polarities are stored as one filter
 * each with an array value, `exact` and `is_not` (logs have no `in` operator); a filter is dropped
 * when its side of the selection empties. Filters the facet doesn't own carry through untouched.
 */
export function setFacetSelection(
    group: UniversalFiltersGroup | undefined,
    target: FacetFilterTarget,
    selection: FacetSelection
): UniversalFiltersGroup {
    // Annotated: negating the type guard would otherwise narrow the survivors to nested groups.
    const values: RailFilterEntry[] = innerFilters(group).filter((f) => !isRailFacetFilter(f, target))
    if (selection.included.length > 0) {
        values.push({ ...target, operator: PropertyOperator.Exact, value: selection.included })
    }
    if (selection.excluded.length > 0) {
        values.push({ ...target, operator: PropertyOperator.IsNot, value: selection.excluded })
    }
    return { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values }] }
}

/** Replace a facet's included values, leaving its exclusions in place. */
export function setFacetIncluded(
    group: UniversalFiltersGroup | undefined,
    target: FacetFilterTarget,
    included: string[]
): UniversalFiltersGroup {
    return setFacetSelection(group, target, { ...facetSelection(group, target), included })
}

/**
 * Advance `value` one step through the facet cycle — unchecked → included → excluded → unchecked —
 * returning a new filterGroup.
 */
export function cycleFacetValue(
    group: UniversalFiltersGroup | undefined,
    target: FacetFilterTarget,
    value: string
): UniversalFiltersGroup {
    const { included, excluded } = facetSelection(group, target)
    if (included.includes(value)) {
        return setFacetSelection(group, target, {
            included: included.filter((v) => v !== value),
            // A value hand-edited into both polarities is already excluded; don't add it twice.
            excluded: excluded.includes(value) ? excluded : [...excluded, value],
        })
    }
    if (excluded.includes(value)) {
        return setFacetSelection(group, target, { included, excluded: excluded.filter((v) => v !== value) })
    }
    return setFacetSelection(group, target, { included: [...included, value], excluded })
}

/**
 * The two `log` filter targets the legacy dedicated query fields fold into. The facet configs and
 * logsViewerFiltersLogic both name their key from here, so the storage key for a column facet's
 * selection is defined once.
 */
export const SEVERITY_LEVEL_FILTER: FacetFilterTarget = { key: 'severity_level', type: PropertyFilterType.Log }
export const SERVICE_NAME_FILTER: FacetFilterTarget = { key: 'service_name', type: PropertyFilterType.Log }
