import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

// Operators that a missing property silently satisfies. The engine reads an absent
// property as an empty value, so "does not equal / does not contain / does not match"
// is true for every event that never set the property. See property.py IS_NOT.
const NEGATED_OPERATORS: ReadonlySet<PropertyOperator> = new Set([
    PropertyOperator.IsNot,
    PropertyOperator.NotIContains,
    PropertyOperator.NotRegex,
])

// Properties the exception pipeline fills on every `$exception` event, so a negated
// filter on one of them is reliable. Kept in sync with the error-tracking options in
// getProductEventPropertyFilterOptions.
const ALWAYS_PRESENT_EXCEPTION_KEYS: ReadonlySet<string> = new Set([
    '$exception_types',
    '$exception_values',
    '$exception_sources',
    '$exception_functions',
    '$exception_handled',
    '$exception_fingerprint',
])

function negatedUnsetKey(filter: AnyPropertyFilter): string | null {
    if (filter.type !== PropertyFilterType.Event && filter.type !== PropertyFilterType.Person) {
        return null
    }
    if (!filter.operator || !NEGATED_OPERATORS.has(filter.operator)) {
        return null
    }
    if (typeof filter.key !== 'string' || ALWAYS_PRESENT_EXCEPTION_KEYS.has(filter.key)) {
        return null
    }
    return filter.key
}

// Collects the keys of event or person property filters that use a negated operator.
// These filters keep every event that never set the property, so the issue list does
// not shrink the way a user expects.
export function findNegatedUnsetPropertyKeys(group: UniversalFiltersGroup): string[] {
    const keys: string[] = []

    const walk = (value: UniversalFiltersGroup['values'][number]): void => {
        if (isUniversalGroupFilterLike(value)) {
            value.values.forEach(walk)
            return
        }
        const key = negatedUnsetKey(value as AnyPropertyFilter)
        if (key !== null) {
            keys.push(key)
        }
    }

    group.values.forEach(walk)
    return Array.from(new Set(keys))
}
