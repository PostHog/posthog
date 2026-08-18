import { taxonomicFilterTypeToPropertyFilterType } from 'lib/components/PropertyFilters/utils'
import {
    hasRecentContext,
    isCompleteRecentPropertyFilter,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroup, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType, PropertyFilterValue, PropertyOperator, UniversalFiltersGroup } from '~/types'

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
export interface LogsFilterTarget {
    type: PropertyFilterType
    key: string
}

// Equality operators carry a value list, so two of them on one attribute and polarity are really one
// filter with more values (`IN` / `NOT IN`). Every other operator (icontains, regex, ranges) is an
// independent predicate that ANDs with its neighbours — two `message icontains` filters mean "matches
// both substrings" — so those are left alone apart from exact duplicates.
const MERGEABLE_OPERATORS: PropertyOperator[] = [PropertyOperator.Exact, PropertyOperator.IsNot]

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
    const entryTarget = filterTarget(entry)
    return entryTarget !== null && entryTarget.type === target.type && entryTarget.key === target.key
}

/** Index of the first filter on `target`, or -1. Lets a caller reuse a filter instead of adding one. */
export function indexOfFilterOn(values: FilterEntry[], target: LogsFilterTarget | null): number {
    if (!target) {
        return -1
    }
    const reconciled = reconcileTarget(values, target)
    return values.findIndex((entry) => isSameTarget(entry, reconciled))
}

function filterValues(filter: ReconcilableFilter): string[] {
    const value = filter.value
    if (Array.isArray(value)) {
        return value.map((v) => String(v))
    }
    return value != null && value !== '' ? [String(value)] : []
}

function withValues(filter: ReconcilableFilter, values: string[]): FilterEntry {
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
    const target = filter ? reconcileTarget(values, { type: filter.type, key: String(filter.key) }) : null
    const operator = filter?.operator

    if (!filter || !target || !operator || !MERGEABLE_OPERATORS.includes(operator)) {
        const alreadyThere =
            filter !== null &&
            values.some((entry) => {
                const existing = asFilter(entry)
                return (
                    existing !== null &&
                    isSameTarget(entry, target as LogsFilterTarget) &&
                    existing.operator === operator &&
                    JSON.stringify(filterValues(existing)) === JSON.stringify(filterValues(filter))
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

    let mergedIntoExisting = false
    const reconciled = values
        .map((entry): FilterEntry | null => {
            const existing = asFilter(entry)
            if (!existing || !isSameTarget(entry, target)) {
                return entry
            }
            if (existing.operator === operator) {
                mergedIntoExisting = true
                const existingValues = filterValues(existing)
                return withValues(existing, [
                    ...existingValues,
                    ...incomingValues.filter((v) => !existingValues.includes(v)),
                ])
            }
            if (existing.operator === OPPOSITE_OPERATOR[operator]) {
                const remaining = filterValues(existing).filter((v) => !incomingValues.includes(v))
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
    | { kind: 'focus'; index: number }
    | { kind: 'new' }

/**
 * Decide how a taxonomic selection applies to the filters already in the bar. Every outcome other
 * than `new` exists because appending unconditionally is what produced contradictory pairs like
 * `service_name ≠ x` beside `service_name = x`, and duplicate empty chips on a filtered attribute.
 *
 * - `merge`: the selection carries a complete filter (a recent), so reconcile it into the group
 * - `valueItem`: the Logs group's free-text item, whose filter the caller builds and records
 * - `focus`: this attribute is already filtered, so open that filter instead of adding another
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
    const existing = indexOfFilterOn(values, selectionTarget(taxonomicGroup, value, item))
    return existing >= 0 ? { kind: 'focus', index: existing } : { kind: 'new' }
}
