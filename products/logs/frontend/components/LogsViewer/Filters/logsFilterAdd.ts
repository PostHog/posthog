import { deepEqual as equal } from 'fast-equals'

import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'
import {
    hasRecentContext,
    isCompleteRecentPropertyFilter,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroup, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { uniqueBy } from 'lib/utils/arrays'

import { PropertyFilterType, PropertyFilterValue, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    EQUALITY_OPERATORS,
    FacetFilterTarget,
    filterValues,
    isSameFilterTarget,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

/**
 * Reconciling a newly picked filter with the filters the logs bar already holds.
 *
 * Adding a filter used to append unconditionally, so picking `service_name = api` while
 * `service_name ≠ api` was active left both in the group and the query returned nothing. The rules
 * below keep the invariant the facet rail keeps (see FacetRail/facetFilters.ts): one filter per
 * attribute and polarity, and no value on both sides at once.
 */

type FilterEntry = UniversalFiltersGroup['values'][number]

// The parts of a property filter this module reads. AnyPropertyFilter is a union whose members
// disagree on `operator` and `value`, and spreading one back produces a type nothing accepts, so the
// entries are narrowed to this shape and cast back at the boundary — same approach as facetFilters.ts.
interface ReconcilableFilter {
    key: string
    type: PropertyFilterType
    operator?: PropertyOperator
    value?: PropertyFilterValue
}

/** The attribute a filter applies to. Two filters reconcile only when both parts match. */
export type LogsFilterTarget = FacetFilterTarget

const OPPOSITE_OPERATOR: Partial<Record<PropertyOperator, PropertyOperator>> = {
    [PropertyOperator.Exact]: PropertyOperator.IsNot,
    [PropertyOperator.IsNot]: PropertyOperator.Exact,
}

function asFilter(entry: FilterEntry): ReconcilableFilter | null {
    if (entry == null || typeof entry !== 'object' || 'values' in entry || !('key' in entry) || !('type' in entry)) {
        return null
    }
    const filter = entry as unknown as ReconcilableFilter
    return filter.key != null && filter.type != null ? filter : null
}

/** The attribute a filter targets, or null for entries that target none (nested groups, entities). */
export function filterTarget(entry: FilterEntry): LogsFilterTarget | null {
    const filter = asFilter(entry)
    return filter ? { type: filter.type, key: String(filter.key) } : null
}

function isSameTarget(entry: FilterEntry, target: LogsFilterTarget): boolean {
    return isSameFilterTarget(filterTarget(entry), target)
}

/**
 * The applied filter a new selection on `target` should reuse, named by the target it is stored
 * under, or null when there is none.
 *
 * Only an equality filter counts. Two `message icontains` filters are a legitimate AND, so picking
 * that attribute again means adding one, not editing the one already there. The reconciled target
 * comes back rather than the caller's, because the two can name different types for one key.
 */
export function appliedEqualityTarget(values: FilterEntry[], target: LogsFilterTarget | null): LogsFilterTarget | null {
    if (!target) {
        return null
    }
    const reconciled = reconcileTarget(values, target)
    const applied = values.some((entry) => {
        const filter = asFilter(entry)
        return (
            filter !== null &&
            isSameTarget(entry, reconciled) &&
            filter.operator !== undefined &&
            EQUALITY_OPERATORS.includes(filter.operator)
        )
    })
    return applied ? reconciled : null
}

// Values are compared as strings because that is what the picker and the URL round-trip them as, but
// the stored value keeps its own type (see filterValues).
function valueKey(value: unknown): string {
    return String(value)
}

function withValues(filter: ReconcilableFilter, values: unknown[]): FilterEntry {
    return { ...filter, value: values } as unknown as FilterEntry
}

/**
 * Add `incoming` to `values`, folding it into an existing filter on the same attribute where that is
 * what the user meant:
 *
 * - an equality filter merges its values into the matching polarity, and drops those values from the
 *   opposite polarity, so `= x` cancels a standing `≠ x` instead of contradicting it
 * - any other operator appends, unless the identical filter is already there
 */
export function mergeFilterIntoValues(values: FilterEntry[], incoming: FilterEntry): FilterEntry[] {
    const filter = asFilter(incoming)
    if (!filter) {
        // A nested group names no attribute, so there is nothing to reconcile it against.
        return [...values, incoming]
    }
    const target = reconcileTarget(values, { type: filter.type, key: String(filter.key) })
    const operator = filter.operator

    if (!operator || !EQUALITY_OPERATORS.includes(operator)) {
        const incomingKeys = filterValues(filter).map(valueKey)
        const alreadyThere = values.some((entry) => {
            const existing = asFilter(entry)
            return (
                existing !== null &&
                isSameTarget(entry, target) &&
                existing.operator === operator &&
                equal(filterValues(existing).map(valueKey), incomingKeys)
            )
        })
        return alreadyThere ? values : [...values, incoming]
    }

    const incomingValues = filterValues(filter)
    if (incomingValues.length === 0) {
        // An equality filter with no value yet is a chip the user still has to fill in, so there is
        // nothing to merge on.
        return [...values, incoming]
    }

    const incomingKeys = incomingValues.map(valueKey)
    let mergedIntoExisting = false
    const reconciled = values
        .map((entry): FilterEntry | null => {
            const existing = asFilter(entry)
            if (!existing || !isSameTarget(entry, target)) {
                return entry
            }
            if (existing.operator === operator) {
                mergedIntoExisting = true
                return withValues(existing, uniqueBy([...filterValues(existing), ...incomingValues], valueKey))
            }
            if (existing.operator === OPPOSITE_OPERATOR[operator]) {
                const remaining = filterValues(existing).filter((v) => !incomingKeys.includes(valueKey(v)))
                return remaining.length > 0 ? withValues(existing, remaining) : null
            }
            return entry
        })
        .filter((entry): entry is FilterEntry => entry !== null)

    if (mergedIntoExisting) {
        return reconciled
    }
    // Adopt the reconciled type so a keyed pick never adds a second chip for a field nobody filtered.
    return [...reconciled, withValues({ ...filter, type: target.type }, incomingValues)]
}

/**
 * The attribute a taxonomic selection would filter on.
 *
 * The group a selection arrives under cannot decide this on its own: both `log` and `log_attribute`
 * filters are recorded under the Log attributes group, and mapping that group back always yields
 * `log_attribute`. A recent recorded from a `service_name` column filter would then resolve to an
 * attribute of the same name, which is a different field. So a filter the selection carries decides
 * the type, and the group is the last resort.
 */
export function selectionTarget(
    taxonomicGroup: TaxonomicFilterGroup,
    value: TaxonomicFilterValue,
    item: any
): LogsFilterTarget | null {
    const carried = hasRecentContext(item) ? asFilter(item._recentContext.propertyFilter as FilterEntry) : null
    const type =
        carried?.type ?? item?.propertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
    const key = carried?.key ?? value
    return type && key != null ? { type, key: String(key) } : null
}

// The two types the picker cannot tell apart: PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE
// records both under the Log attributes group, so mapping that group back can only ever answer
// `log_attribute`. Resource attributes map to a group of their own and stay distinct.
const AMBIGUOUS_TYPES: PropertyFilterType[] = [PropertyFilterType.Log, PropertyFilterType.LogAttribute]

/**
 * The attribute an incoming filter reconciles against. When no filter on that exact type and key is
 * applied but one shares the key under the ambiguous pair above, the applied one wins: two filters
 * that both render `service_name = api` read as a duplicate whichever field each one queries.
 */
function reconcileTarget(values: FilterEntry[], target: LogsFilterTarget): LogsFilterTarget {
    if (values.some((entry) => isSameTarget(entry, target)) || !AMBIGUOUS_TYPES.includes(target.type)) {
        return target
    }
    const sameKey = values
        .map(asFilter)
        .find((filter) => filter !== null && String(filter.key) === target.key && AMBIGUOUS_TYPES.includes(filter.type))
    return sameKey ? { type: sameKey.type, key: String(sameKey.key) } : target
}

/** What the filter bar should do with a dropdown selection, given the filters it already holds. */
export type LogsSelection =
    | { kind: 'merge'; filter: FilterEntry }
    | { kind: 'valueItem' }
    | { kind: 'focus'; target: LogsFilterTarget }
    | { kind: 'new' }

/**
 * Decide how a taxonomic selection applies to the filters already in the bar. Every outcome other
 * than `new` exists because appending unconditionally is what produced contradictory pairs like
 * `service_name ≠ x` beside `service_name = x`, and duplicate empty chips on a filtered attribute.
 *
 * - `merge`: the selection carries a complete filter (a recent), so reconcile it into the group
 * - `valueItem`: the Logs group's free-text item, whose filter the caller builds and records
 * - `focus`: this attribute already has an equality filter, so open it instead of adding another
 * - `new`: nothing on this attribute yet, so let the shared filter logic build it
 */
export function logsSelection(
    values: FilterEntry[],
    taxonomicGroup: TaxonomicFilterGroup,
    value: TaxonomicFilterValue,
    item: any
): LogsSelection {
    const recentFilter = hasRecentContext(item) ? item._recentContext.propertyFilter : undefined
    // Only a recent that carries something to apply merges. A recent without a value is the bare-key
    // row the picker derives from a complete one, and it falls through to the reuse path below. The
    // shared addGroupFilter pushes any filter a recent carries, so an incomplete one has to be caught
    // here or it lands as a second chip on an attribute that already has one.
    if (recentFilter && isCompleteRecentPropertyFilter(recentFilter)) {
        return { kind: 'merge', filter: recentFilter as FilterEntry }
    }
    if (item?.value !== undefined) {
        return { kind: 'valueItem' }
    }
    // A row the backend surfaced because the search matched a *value* carries it as `matchedValue`,
    // and the shared filter builder pre-fills it (createDefaultPropertyFilter). Without this it looks
    // like a bare key, and picking one while the attribute is already filtered would drop the value.
    const target = selectionTarget(taxonomicGroup, value, item)
    if (target && item?.matchedOn === 'value' && typeof item.matchedValue === 'string') {
        return {
            kind: 'merge',
            filter: {
                ...target,
                operator: PropertyOperator.Exact,
                value: [item.matchedValue],
            } as unknown as FilterEntry,
        }
    }
    // The applied filter's own target, not the one derived from the group: the bar matches chips by
    // target, and the derived type can disagree with the applied one (see reconcileTarget).
    const matched = appliedEqualityTarget(values, target)
    return matched ? { kind: 'focus', target: matched } : { kind: 'new' }
}
