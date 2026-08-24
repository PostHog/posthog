import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

export const SNOOZE_DURATIONS = [
    { label: '30 minutes', minutes: 30 },
    { label: '1 hour', minutes: 60 },
    { label: '4 hours', minutes: 240 },
    { label: '24 hours', minutes: 1440 },
]

export function hasAnyFilter(serviceNames: string[], errorOnly: boolean, filterGroup: UniversalFiltersGroup): boolean {
    return serviceNames.length > 0 || errorOnly || filterGroup.values.length > 0
}

export function buildAlertFilters(
    serviceNames: string[],
    errorOnly: boolean,
    filterGroup: UniversalFiltersGroup
): Record<string, unknown> {
    const filters: Record<string, unknown> = {}
    if (serviceNames.length > 0) {
        filters.serviceNames = serviceNames
    }
    if (errorOnly) {
        filters.errorOnly = true
    }
    if (filterGroup.values.length > 0) {
        filters.filterGroup = {
            type: FilterLogicalOperator.And,
            values: [filterGroup],
        }
    }
    return filters
}
