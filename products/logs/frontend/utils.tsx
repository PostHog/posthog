import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { capitalizeFirstLetter } from 'lib/utils'

import { AnyPropertyFilter } from '~/types'

import { formatDateRangeLabel } from 'products/logs/frontend/components/LogsViewer/Filters/LogsDateRangePicker/utils'

export function formatFilterGroupValues(filterGroup: Record<string, any> | undefined): string[] {
    const group = filterGroup?.values?.[0]
    if (!group || !('values' in group)) {
        return []
    }

    return group.values.filter(isValidPropertyFilter).map((filter: AnyPropertyFilter) => {
        const key = filter.key || '?'
        const value = Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value ?? '')
        const truncatedValue = value.length > 15 ? `${value.slice(0, 15)}...` : value
        return `${key}=${truncatedValue}`
    })
}

export interface FiltersSummaryLine {
    label: string
    value: string
}

export function getFiltersSummaryLines(filters: Record<string, any>): FiltersSummaryLine[] {
    const lines: FiltersSummaryLine[] = []

    if (filters.dateRange) {
        const label = formatDateRangeLabel(filters.dateRange, Intl.DateTimeFormat().resolvedOptions().timeZone, [])
        lines.push({ label: 'Date range', value: label })
    }

    if (filters.severityLevels?.length) {
        lines.push({
            label: 'Severity',
            value: filters.severityLevels.map((l: string) => capitalizeFirstLetter(l)).join(', '),
        })
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

    if (filters.searchTerm) {
        const truncated = filters.searchTerm.length > 30 ? `${filters.searchTerm.slice(0, 30)}...` : filters.searchTerm
        lines.push({ label: 'Search', value: `"${truncated}"` })
    }

    const attributeFilters = formatFilterGroupValues(filters.filterGroup)
    if (attributeFilters.length > 0) {
        lines.push({
            label: attributeFilters.length === 1 ? 'Filter' : 'Filters',
            value: attributeFilters.join(', '),
        })
    }

    return lines
}

const DISTINCT_ID_KEYS = [
    'distinct.id',
    'distinct_id',
    'distinctId',
    'distinctID',
    'posthogDistinctId',
    'posthogDistinctID',
    'posthog_distinct_id',
    'posthog.distinct.id',
    'posthog.distinct_id',
]
const SESSION_ID_KEYS = [
    'session.id',
    'session_id',
    'sessionId',
    'sessionID',
    '$session_id',
    'posthogSessionId',
    'posthogSessionID',
    'posthog_session_id',
    'posthog.session.id',
    'posthog.session_id',
]

function matchesKey(key: string, candidates: string[]): boolean {
    return candidates.some((candidate) => key === candidate || key.endsWith(`.${candidate}`))
}

export function isDistinctIdKey(key: string): boolean {
    return matchesKey(key, DISTINCT_ID_KEYS)
}

export function isSessionIdKey(key: string): boolean {
    return matchesKey(key, SESSION_ID_KEYS)
}

export function getSessionIdFromLogAttributes(
    attributes: Record<string, unknown> | undefined,
    resourceAttributes: Record<string, unknown> | undefined
): string | null {
    for (const [key, value] of Object.entries(attributes || {})) {
        if (isSessionIdKey(key) && value) {
            return String(value)
        }
    }
    for (const [key, value] of Object.entries(resourceAttributes || {})) {
        if (isSessionIdKey(key) && value) {
            return String(value)
        }
    }
    return null
}
