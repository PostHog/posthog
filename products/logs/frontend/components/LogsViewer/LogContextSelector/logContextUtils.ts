import { dayjs } from 'lib/dayjs'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'
import { ParsedLogMessage } from 'products/logs/frontend/types'
import { getSessionIdWithKey } from 'products/logs/frontend/utils'

export type LogContextType = 'surrounding_service' | 'surrounding_all' | 'trace' | 'session'

export interface LogContextOption {
    type: LogContextType
    label: string
    description: string
}

const SURROUNDING_WINDOW_MINUTES = 1
const TRACE_WINDOW_MINUTES = 5
const SESSION_WINDOW_MINUTES = 30

function getServiceName(log: ParsedLogMessage): string | null {
    const resourceAttrs = log.resource_attributes as Record<string, unknown> | undefined
    const serviceName = resourceAttrs?.['service.name']
    return serviceName ? String(serviceName) : null
}

function getSessionMatch(
    log: ParsedLogMessage
): { key: string; value: string; source: 'attribute' | 'resource_attribute' } | null {
    return getSessionIdWithKey(log.attributes, log.resource_attributes as Record<string, unknown> | undefined)
}

function buildDateRangeAround(timestamp: string, windowMinutes: number): { date_from: string; date_to: string } {
    const center = dayjs(timestamp)
    return {
        date_from: center.subtract(windowMinutes, 'minute').toISOString(),
        date_to: center.add(windowMinutes, 'minute').toISOString(),
    }
}

function buildFilterGroup(key: string, value: string, propertyType: PropertyFilterType): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        key,
                        value: [value],
                        operator: PropertyOperator.Exact,
                        type: propertyType,
                    } as any,
                ],
            },
        ],
    }
}

export function getAvailableContexts(log: ParsedLogMessage): LogContextOption[] {
    const contexts: LogContextOption[] = []
    const serviceName = getServiceName(log)

    if (serviceName) {
        contexts.push({
            type: 'surrounding_service',
            label: 'View surrounding logs',
            description: `Logs from ${serviceName} around this time`,
        })
    }

    contexts.push({
        type: 'surrounding_all',
        label: 'View all logs at this time',
        description: 'All logs across services around this time',
    })

    if (log.trace_id) {
        contexts.push({
            type: 'trace',
            label: 'View trace logs',
            description: 'All logs sharing this trace ID',
        })
    }

    if (getSessionMatch(log)) {
        contexts.push({
            type: 'session',
            label: 'View session logs',
            description: 'All logs from this session',
        })
    }

    return contexts
}

export function buildContextFilters(log: ParsedLogMessage, contextType: LogContextType): Partial<LogsViewerFilters> {
    const base: Pick<LogsViewerFilters, 'searchTerm' | 'severityLevels'> = {
        searchTerm: '',
        severityLevels: [],
    }

    switch (contextType) {
        case 'surrounding_service': {
            const serviceName = getServiceName(log)
            return {
                ...base,
                dateRange: buildDateRangeAround(log.timestamp, SURROUNDING_WINDOW_MINUTES),
                serviceNames: serviceName ? [serviceName] : [],
            }
        }
        case 'surrounding_all': {
            return {
                ...base,
                dateRange: buildDateRangeAround(log.timestamp, SURROUNDING_WINDOW_MINUTES),
                serviceNames: [],
            }
        }
        case 'trace': {
            return {
                ...base,
                dateRange: buildDateRangeAround(log.timestamp, TRACE_WINDOW_MINUTES),
                filterGroup: buildFilterGroup('trace_id', log.trace_id, PropertyFilterType.Log),
            }
        }
        case 'session': {
            const session = getSessionMatch(log)
            return {
                ...base,
                dateRange: buildDateRangeAround(log.timestamp, SESSION_WINDOW_MINUTES),
                filterGroup: session
                    ? buildFilterGroup(
                          session.key,
                          session.value,
                          session.source === 'attribute'
                              ? PropertyFilterType.LogAttribute
                              : PropertyFilterType.LogResourceAttribute
                      )
                    : undefined,
            }
        }
    }
}
