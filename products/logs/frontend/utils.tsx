import { formatDateRangeLabel } from 'lib/components/DateFilter/DateRangePicker/utils'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS } from 'products/logs/frontend/logsConfigLogic'

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

// Configured keys (the team's `logs_session_id_attribute_keys` setting) match exactly;
// only the built-in convention list gets dot-suffix matching.
export function isSessionIdKey(key: string, configuredKeys?: string[]): boolean {
    return (configuredKeys ?? []).includes(key) || matchesKey(key, SESSION_ID_KEYS)
}

export interface SessionIdMatch {
    key: string
    value: string
    source: 'attribute' | 'resource_attribute'
}

export function getSessionIdWithKey(
    attributes: Record<string, unknown> | undefined,
    resourceAttributes: Record<string, unknown> | undefined,
    configuredKeys?: string[]
): SessionIdMatch | null {
    // Configured keys win over the built-in conventions, in list order: for each key,
    // attributes are checked before resource_attributes, and the first value found wins.
    for (const key of configuredKeys ?? []) {
        const attributeValue = attributes?.[key]
        if (attributeValue) {
            return { key, value: String(attributeValue), source: 'attribute' }
        }
        const resourceAttributeValue = resourceAttributes?.[key]
        if (resourceAttributeValue) {
            return { key, value: String(resourceAttributeValue), source: 'resource_attribute' }
        }
    }
    // Built-in convention fallback only — the configured-key pass already ran above,
    // so isSessionIdKey is deliberately called without configuredKeys here.
    for (const [key, value] of Object.entries(attributes || {})) {
        if (isSessionIdKey(key) && value) {
            return { key, value: String(value), source: 'attribute' }
        }
    }
    for (const [key, value] of Object.entries(resourceAttributes || {})) {
        if (isSessionIdKey(key) && value) {
            return { key, value: String(value), source: 'resource_attribute' }
        }
    }
    return null
}

export function getSessionIdFromLogAttributes(
    attributes: Record<string, unknown> | undefined,
    resourceAttributes: Record<string, unknown> | undefined,
    configuredKeys?: string[]
): string | null {
    return getSessionIdWithKey(attributes, resourceAttributes, configuredKeys)?.value ?? null
}

// Matches SESSION_WINDOW_MINUTES in logContextUtils — wide enough to cover a session
// around a single event without drowning it in unrelated logs.
const SESSION_LOGS_WINDOW_MINUTES = 30

// Builds a logs-scene URL filtered to one session, for linking in from other products
// (error tracking, session replay). Filters on the team's configured session ID keys
// (OR across keys, exact match), defaulting to the SDK convention; a timestamp scopes
// the date range to ±30 minutes so old sessions aren't hidden by the default range.
export function buildLogsSessionUrl(sessionId: string, configuredKeys?: string[], timestamp?: string): string {
    const keys = configuredKeys?.length ? configuredKeys : DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS
    const filterGroup = {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.Or,
                values: keys.map((key) => ({
                    key,
                    value: [sessionId],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.LogAttribute,
                })),
            },
        ],
    }
    const params = new URLSearchParams({ filterGroup: JSON.stringify(filterGroup) })
    if (timestamp) {
        const center = dayjs(timestamp)
        params.set(
            'dateRange',
            JSON.stringify({
                date_from: center.subtract(SESSION_LOGS_WINDOW_MINUTES, 'minute').toISOString(),
                date_to: center.add(SESSION_LOGS_WINDOW_MINUTES, 'minute').toISOString(),
            })
        )
    }
    return `${urls.logs()}?${params.toString()}`
}
