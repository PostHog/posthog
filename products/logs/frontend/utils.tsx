import { formatDateRangeLabel } from 'lib/components/DateFilter/DateRangePicker/utils'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import {
    FacetFilterTarget,
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    facetSelection,
} from 'products/logs/frontend/components/LogsViewer/FacetRail/facetFilters'

/**
 * A level or service selection reaches a summary in one of two shapes: the dedicated
 * `severityLevels`/`serviceNames` field, which saved views, alerts and persisted filter history can
 * carry, or the `exact` log filter in `filterGroup`, which is what the viewer writes. Read both, so
 * an entry in either shape summarizes identically.
 */
export function summaryColumnSelection(
    filters: Record<string, any>,
    legacyField: 'severityLevels' | 'serviceNames',
    target: FacetFilterTarget
): string[] {
    const legacy = filters[legacyField]
    if (Array.isArray(legacy) && legacy.length > 0) {
        return legacy as string[]
    }
    return facetSelection(filters.filterGroup, target).included
}

/**
 * One `key=value` string per property filter in the group. `skipIncludes` drops the `exact` filters
 * under the given targets, for callers that summarize those selections under their own label.
 */
export function formatFilterGroupValues(
    filterGroup: Record<string, any> | undefined,
    skipIncludes: FacetFilterTarget[] = []
): string[] {
    const group = filterGroup?.values?.[0]
    if (!group || !('values' in group)) {
        return []
    }

    const isSkipped = (filter: AnyPropertyFilter): boolean =>
        'operator' in filter &&
        filter.operator === PropertyOperator.Exact &&
        skipIncludes.some((target) => filter.type === target.type && filter.key === target.key)

    return group.values
        .filter(isValidPropertyFilter)
        .filter((filter: AnyPropertyFilter) => !isSkipped(filter))
        .map((filter: AnyPropertyFilter) => {
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

    const severityLevels = summaryColumnSelection(filters, 'severityLevels', SEVERITY_LEVEL_FILTER)
    if (severityLevels.length > 0) {
        lines.push({
            label: 'Severity',
            value: severityLevels.map((l: string) => capitalizeFirstLetter(l)).join(', '),
        })
    }

    const serviceNames = summaryColumnSelection(filters, 'serviceNames', SERVICE_NAME_FILTER)
    if (serviceNames.length > 0) {
        const maxDisplayed = 3
        const displayed = serviceNames.slice(0, maxDisplayed)
        const remaining = serviceNames.length - displayed.length
        const serviceText = displayed.join(', ')
        lines.push({
            label: serviceNames.length === 1 ? 'Service' : 'Services',
            value: remaining > 0 ? `${serviceText} +${remaining} more` : serviceText,
        })
    }

    if (filters.searchTerm) {
        const truncated = filters.searchTerm.length > 30 ? `${filters.searchTerm.slice(0, 30)}...` : filters.searchTerm
        lines.push({ label: 'Search', value: `"${truncated}"` })
    }

    // Skips the `exact` log filters the Severity and Service lines above already cover, so a
    // group-stored selection isn't reported twice. Only where the line came from the group: a line
    // read off the legacy field says nothing about the group, so skipping there would drop a
    // `severity_level =` chip from the summary entirely. Exclusions always show here.
    const usedLegacyField = (legacyField: 'severityLevels' | 'serviceNames'): boolean =>
        Array.isArray(filters[legacyField]) && filters[legacyField].length > 0
    const attributeFilters = formatFilterGroupValues(filters.filterGroup, [
        ...(usedLegacyField('severityLevels') ? [] : [SEVERITY_LEVEL_FILTER]),
        ...(usedLegacyField('serviceNames') ? [] : [SERVICE_NAME_FILTER]),
    ])
    if (attributeFilters.length > 0) {
        lines.push({
            label: attributeFilters.length === 1 ? 'Filter' : 'Filters',
            value: attributeFilters.join(', '),
        })
    }

    return lines
}

// Mirror of DISTINCT_ID_ATTRIBUTE_KEY_CONVENTIONS in products/logs/backend/models.py — keep the
// two in sync. Values under these keys render as clickable person links here, and the person
// Logs tab scopes on them server-side so those logs appear on the person's tab.
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
// Some pipelines emit `posthogSessionId` even though no SDK does. Removing it breaks them.
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

// Configured keys (the team's `logs_distinct_id_attribute_keys` setting) match exactly;
// only the built-in convention list gets dot-suffix matching.
export function isDistinctIdKey(key: string, configuredKeys?: string[]): boolean {
    return (configuredKeys ?? []).includes(key) || matchesKey(key, DISTINCT_ID_KEYS)
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

// Wide enough to cover a session around a single event without drowning it in unrelated logs.
export const SESSION_LOGS_WINDOW_MINUTES = 30

export function buildDateRangeAround(timestamp: string, windowMinutes: number): { date_from: string; date_to: string } {
    const center = dayjs(timestamp)
    return {
        date_from: center.subtract(windowMinutes, 'minute').toISOString(),
        date_to: center.add(windowMinutes, 'minute').toISOString(),
    }
}

// Builds logs viewer filters scoped to one session, for other products surfacing logs
// (error tracking, session replay). Filters (OR across keys, exact match) on the team's
// configured session ID keys plus the SESSION_ID_KEYS conventions, deduped, configured
// first — the same breadth `getSessionIdWithKey` resolves, so a team whose stored key their
// pipeline never emits still matches. Literal keys only: an exact filter can't express the
// dot-suffix variants `matchesKey` allows. A timestamp scopes the date range to ±30 minutes
// so old sessions aren't hidden by the default range.
export function buildLogsSessionFilters(
    sessionId: string,
    configuredKeys?: string[],
    timestamp?: string
): Partial<LogsViewerFilters> {
    const keys = Array.from(new Set([...(configuredKeys ?? []), ...SESSION_ID_KEYS]))
    const filters: Partial<LogsViewerFilters> = {
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.Or,
                    // Each key is queried in both maps, because getSessionIdWithKey renders the
                    // session link off attributes or resource_attributes. Person scoping resolves
                    // distinct ids across both maps for the same reason.
                    values: keys.flatMap((key) => [
                        {
                            key,
                            value: [sessionId],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.LogAttribute,
                        },
                        {
                            key,
                            value: [sessionId],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.LogResourceAttribute,
                        },
                    ]),
                },
            ],
        },
    }
    if (timestamp) {
        filters.dateRange = buildDateRangeAround(timestamp, SESSION_LOGS_WINDOW_MINUTES)
    }
    return filters
}
