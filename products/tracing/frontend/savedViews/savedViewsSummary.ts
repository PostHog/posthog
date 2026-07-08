import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter } from '~/types'

export interface FiltersSummaryLine {
    label: string
    value: string
}

function formatFilterGroupValues(filterGroup: Record<string, any> | undefined): string[] {
    const groups = filterGroup?.values
    if (!Array.isArray(groups)) {
        return []
    }

    // The outer `values` array can hold multiple sibling groups — flatten leaf property filters
    // across all of them so the summary doesn't silently drop groups past the first.
    return groups
        .filter((group) => group && Array.isArray(group.values))
        .flatMap((group) => group.values.filter(isValidPropertyFilter))
        .map((filter: AnyPropertyFilter) => {
            const key = filter.key || '?'
            const value = Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value ?? '')
            const truncatedValue = value.length > 15 ? `${value.slice(0, 15)}...` : value
            return `${key}=${truncatedValue}`
        })
}

// Compact, human-readable summary of a saved view's filters — shown in the list and save dialog so a
// user can tell views apart without loading them. Mirrors the shape produced by tracingFiltersLogic.
export function getTracingFiltersSummaryLines(filters: Record<string, any>): FiltersSummaryLine[] {
    const lines: FiltersSummaryLine[] = []

    if (filters.dateRange?.date_from) {
        const value = filters.dateRange.date_to
            ? `${filters.dateRange.date_from} → ${filters.dateRange.date_to}`
            : filters.dateRange.date_from
        lines.push({ label: 'Date range', value })
    }

    if (filters.serviceNames?.length) {
        const maxDisplayed = 3
        const displayed = filters.serviceNames.slice(0, maxDisplayed)
        const remaining = filters.serviceNames.length - displayed.length
        const serviceText = displayed.join(', ')
        lines.push({
            label: filters.serviceNames.length === 1 ? 'Service' : 'Services',
            value: remaining > 0 ? `${serviceText} +${remaining} more` : serviceText,
        })
    }

    const attributeFilters = formatFilterGroupValues(filters.filterGroup)
    if (attributeFilters.length > 0) {
        lines.push({
            label: attributeFilters.length === 1 ? 'Filter' : 'Filters',
            value: attributeFilters.join(', '),
        })
    }

    if (filters.viewMode) {
        lines.push({ label: 'View', value: filters.viewMode === 'spans' ? 'Spans' : 'Traces' })
    }

    if (filters.orderBy) {
        const direction = filters.orderDirection === 'ASC' ? 'ascending' : 'descending'
        lines.push({ label: 'Sort', value: `${filters.orderBy} (${direction})` })
    }

    return lines
}
