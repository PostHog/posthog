/**
 * Reconciling a filter added from a span attribute row with the filters the bar already holds.
 *
 * The row buttons used to append unconditionally, so clicking `+` twice left two identical chips,
 * and clicking `+` after `-` on the same value left `attr = x` beside `attr ≠ x`, which matches no
 * span. The rules below keep the invariant the facet rail keeps (see FacetRail/facets.ts): one
 * filter per attribute and polarity, and no value on both sides at once.
 *
 * Logs holds the same rules in Filters/logsFilterAdd.ts, over a superset that also reconciles the
 * ambiguous `log` / `log_attribute` pair its picker produces. Two copies is what the products
 * convention allows; a third consumer is the point to lift the shared core into lib/.
 */

import { uniqueBy } from 'lib/utils/arrays'

import { PropertyFilterType, PropertyFilterValue, PropertyOperator, UniversalFiltersGroup } from '~/types'

type FilterEntry = UniversalFiltersGroup['values'][number]

// The parts of a property filter this module reads. AnyPropertyFilter is a union whose members
// disagree on `operator` and `value`, and spreading one back produces a type nothing accepts, so
// entries are narrowed to this shape and cast back at the boundary — same approach as facets.ts.
interface ReconcilableFilter {
    key: string
    type: PropertyFilterType
    operator?: PropertyOperator
    value?: PropertyFilterValue
}

// A row button only ever writes one of these two. Any other operator on the same key (an
// `icontains` typed into the bar) is a legitimate AND, so it neither absorbs nor blocks a click.
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

// Values are compared as strings because that is what the attribute rows and the URL round-trip
// them as, but the stored value keeps its own type.
function valueKey(value: unknown): string {
    return String(value)
}

function filterValues(filter: ReconcilableFilter): unknown[] {
    if (Array.isArray(filter.value)) {
        return filter.value
    }
    return filter.value != null ? [filter.value] : []
}

function withValues(filter: ReconcilableFilter, values: unknown[]): FilterEntry {
    return { ...filter, value: values } as unknown as FilterEntry
}

export interface SpanFilterMerge {
    /** The inner group's values with `incoming` folded in. */
    values: FilterEntry[]
    /**
     * The entry that ended up carrying the incoming value — the one just appended, or the existing
     * filter it merged into. The bar addresses chips by identity, so it needs this rather than an
     * index.
     */
    filter: FilterEntry
}

/**
 * Add `incoming` to `values`, folding it into an existing filter on the same attribute where that is
 * what the click meant:
 *
 * - an equality filter merges its values into the matching polarity, so clicking the same row again
 *   changes nothing, and drops those values from the opposite polarity, so `= x` cancels a standing
 *   `≠ x` instead of contradicting it
 * - anything else appends
 */
export function mergeSpanFilter(values: FilterEntry[], incoming: FilterEntry): SpanFilterMerge {
    const filter = asFilter(incoming)
    const operator = filter?.operator
    const opposite = operator ? OPPOSITE_OPERATOR[operator] : undefined
    const incomingValues = filter ? filterValues(filter) : []
    if (!filter || !operator || !opposite || incomingValues.length === 0) {
        return { values: [...values, incoming], filter: incoming }
    }

    const incomingKeys = incomingValues.map(valueKey)
    const reconciled: FilterEntry[] = []
    let merged: FilterEntry | null = null

    for (const entry of values) {
        const existing = asFilter(entry)
        if (!existing || existing.type !== filter.type || existing.key !== filter.key) {
            reconciled.push(entry)
            continue
        }
        if (existing.operator === operator) {
            merged = withValues(existing, uniqueBy([...filterValues(existing), ...incomingValues], valueKey))
            reconciled.push(merged)
            continue
        }
        if (existing.operator === opposite) {
            const remaining = filterValues(existing).filter((v) => !incomingKeys.includes(valueKey(v)))
            if (remaining.length > 0) {
                reconciled.push(withValues(existing, remaining))
            }
            continue
        }
        reconciled.push(entry)
    }

    if (merged) {
        return { values: reconciled, filter: merged }
    }
    return { values: [...reconciled, incoming], filter: incoming }
}
