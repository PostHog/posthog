import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { PropertyFilterType, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

// Filter keys the query reads from a top-level column when the filter is typed `log` (backend
// `COLUMN_FILTER_FACET_FIELDS` in `products/logs/backend/logs_query_runner.py`). The Log attributes
// tab offers the same keys, and a pick there builds a `log_attribute` filter, so the query looks up
// `attributes['service_name']`, which no row has, and returns nothing. The chip renders only the key,
// so it reads exactly like the working filter the facet rail writes. Pin these keys to `log` whichever
// tab they came from, as resolveGroupBySource does for group-by. Only reserved column names are
// pinned: any other key can legitimately name distinct log and resource attributes.
// This mirrors the backend dict by hand; `columnFilters.test.ts` fails if the two drift apart.
export const COLUMN_FILTER_KEYS = new Set<string>(['severity_level', 'service_name'])

const ATTRIBUTE_FILTER_TYPES: (PropertyFilterType | undefined)[] = [
    PropertyFilterType.LogAttribute,
    PropertyFilterType.LogResourceAttribute,
]

function pinColumnFilter(value: UniversalFiltersGroupValue): UniversalFiltersGroupValue {
    if (isUniversalGroupFilterLike(value)) {
        return pinColumnFilters(value)
    }
    if ('key' in value && COLUMN_FILTER_KEYS.has(String(value.key)) && ATTRIBUTE_FILTER_TYPES.includes(value.type)) {
        return { ...value, type: PropertyFilterType.Log } as UniversalFiltersGroupValue
    }
    return value
}

/** The group with every attribute filter on a reserved column key retyped to `log`. */
export function pinColumnFilters(group: UniversalFiltersGroup): UniversalFiltersGroup {
    const values = group.values.map(pinColumnFilter)
    // Hand back the same group when nothing moved, so an unchanged group does not reload the query.
    return values.every((value, index) => value === group.values[index]) ? group : { ...group, values }
}
