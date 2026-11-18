import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { PropertyFilterType, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import {
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

// Keys the query reads from a top-level column when the filter is typed `log` (backend
// `COLUMN_FILTER_FACET_FIELDS` in `products/logs/backend/logs_query_runner.py`). A pick from the Log
// attributes tab types them `log_attribute`, so the query reads a missing attribute and returns
// nothing. Pin them to `log`, as resolveGroupBySource does for group-by. Resource attributes are not
// pinned: they have a picker group of their own, so a resource attribute of the same name is a
// distinct field (see reconcileTarget in logsFilterAdd.ts).
// `columnFilters.test.ts` fails if this set drifts from the backend dict.
export const COLUMN_FILTER_KEYS = new Set<string>([SEVERITY_LEVEL_FILTER.key, SERVICE_NAME_FILTER.key])

function pinColumnFilter(value: UniversalFiltersGroupValue): UniversalFiltersGroupValue {
    // A URL or saved view can carry a malformed entry. Leave it as it is rather than throw in the reducer.
    if (value == null || typeof value !== 'object') {
        return value
    }
    if (isUniversalGroupFilterLike(value)) {
        return pinColumnFilters(value)
    }
    if ('key' in value && COLUMN_FILTER_KEYS.has(String(value.key)) && value.type === PropertyFilterType.LogAttribute) {
        return { ...value, type: PropertyFilterType.Log } as UniversalFiltersGroupValue
    }
    return value
}

/** The group with every log attribute filter on a column key retyped to `log`. */
export function pinColumnFilters(group: UniversalFiltersGroup): UniversalFiltersGroup {
    const values = group.values.map(pinColumnFilter)
    // Hand back the same group when nothing moved, so an unchanged group does not reload the query.
    return values.every((value, index) => value === group.values[index]) ? group : { ...group, values }
}
