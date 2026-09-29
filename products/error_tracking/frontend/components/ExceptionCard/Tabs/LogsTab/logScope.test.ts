import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import type { ExceptionLogsScope } from '../../exceptionCardLogic'
import {
    buildExceptionLogPinnedFilters,
    getAvailableExceptionLogScopes,
    getEffectiveExceptionLogScope,
} from './logScope'

const ids = { traceId: 'trace-abc', spanId: 'span-xyz', sessionId: 'session-123' }

describe('exception log scope', () => {
    it.each([
        [ids, ['trace', 'span', 'session', 'window']],
        [{ sessionId: ids.sessionId }, ['session', 'window']],
        [{ spanId: ids.spanId }, ['window']],
    ] as const)('offers only the correlation scopes supported by %o', (correlationIds, expectedScopes) => {
        expect(getAvailableExceptionLogScopes(correlationIds)).toEqual(expectedScopes)
    })

    it.each<[string, ExceptionLogsScope, Partial<typeof ids>, ExceptionLogsScope]>([
        ['keeps an available selection', 'span', ids, 'span'],
        ['defaults to the trace', 'span', { traceId: ids.traceId, sessionId: ids.sessionId }, 'trace'],
        ['falls back to the session', 'trace', { sessionId: ids.sessionId }, 'session'],
        ['falls back to the time window', 'trace', {}, 'window'],
    ])('%s', (_label, selectedScope, correlationIds, expectedScope) => {
        const availableScopes = getAvailableExceptionLogScopes(correlationIds)

        expect(getEffectiveExceptionLogScope(selectedScope, availableScopes)).toBe(expectedScope)
    })

    it('pins a trace scope to the native trace ID column', () => {
        expect(buildExceptionLogPinnedFilters('trace', ids)).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'trace_id',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['trace-abc'],
                },
            ],
        })
    })

    it('pins a span scope to both the trace and span ID columns', () => {
        expect(buildExceptionLogPinnedFilters('span', ids)).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    key: 'trace_id',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['trace-abc'],
                },
                {
                    key: 'span_id',
                    type: PropertyFilterType.Log,
                    operator: PropertyOperator.Exact,
                    value: ['span-xyz'],
                },
            ],
        })
    })
})
