import {
    FilterLogicalOperator,
    type LogPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    type UniversalFiltersGroup,
} from '~/types'

import type { ExceptionLogsScope } from '../../exceptionCardLogic'

export interface ExceptionLogCorrelationIds {
    sessionId?: string
    spanId?: string
    traceId?: string
}

function logIdFilter(key: 'span_id' | 'trace_id', value: string): LogPropertyFilter {
    return {
        key,
        type: PropertyFilterType.Log,
        operator: PropertyOperator.Exact,
        value: [value],
    } as LogPropertyFilter
}

export function getAvailableExceptionLogScopes({
    sessionId,
    spanId,
    traceId,
}: ExceptionLogCorrelationIds): ExceptionLogsScope[] {
    const scopes: ExceptionLogsScope[] = []
    if (traceId) {
        scopes.push('trace')
    }
    if (traceId && spanId) {
        scopes.push('span')
    }
    if (sessionId) {
        scopes.push('session')
    }
    scopes.push('window')
    return scopes
}

export function getEffectiveExceptionLogScope(
    selectedScope: ExceptionLogsScope,
    availableScopes: ExceptionLogsScope[]
): ExceptionLogsScope {
    return availableScopes.includes(selectedScope) ? selectedScope : (availableScopes[0] ?? 'window')
}

export function buildExceptionLogPinnedFilters(
    scope: ExceptionLogsScope,
    { spanId, traceId }: ExceptionLogCorrelationIds
): UniversalFiltersGroup | undefined {
    if (scope === 'trace' && traceId) {
        return {
            type: FilterLogicalOperator.And,
            values: [logIdFilter('trace_id', traceId)],
        }
    }

    if (scope === 'span' && traceId && spanId) {
        return {
            type: FilterLogicalOperator.And,
            values: [logIdFilter('trace_id', traceId), logIdFilter('span_id', spanId)],
        }
    }

    return undefined
}
