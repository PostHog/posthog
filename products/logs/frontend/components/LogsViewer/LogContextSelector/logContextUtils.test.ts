import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import { buildContextFilters, getAvailableContexts, LogContextType } from './logContextUtils'

const makeLog = (overrides: Partial<ParsedLogMessage> = {}): ParsedLogMessage => ({
    uuid: 'test-uuid',
    trace_id: '',
    span_id: '',
    body: 'test log message',
    attributes: {},
    resource_attributes: {},
    timestamp: '2026-03-24T12:00:00.000Z',
    observed_timestamp: '2026-03-24T12:00:00.000Z',
    severity_text: 'info',
    severity_number: 9,
    level: 'info',
    instrumentation_scope: '',
    event_name: '',
    cleanBody: 'test log message',
    parsedBody: null,
    originalLog: {} as any,
    ...overrides,
})

const makeFilterGroup = (key: string, value: string, type: PropertyFilterType): any => ({
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [{ key, value: [value], operator: PropertyOperator.Exact, type }],
        },
    ],
})

describe('getAvailableContexts', () => {
    it.each([
        ['bare log', {}, ['surrounding_all']],
        [
            'with service',
            { resource_attributes: { 'service.name': 'api' } },
            ['surrounding_service', 'surrounding_all'],
        ],
        ['with trace', { trace_id: 'abc' }, ['surrounding_all', 'trace']],
        ['with session', { attributes: { 'session.id': 's1' } }, ['surrounding_all', 'session']],
        [
            'all metadata',
            { resource_attributes: { 'service.name': 'api' }, trace_id: 'abc', attributes: { 'session.id': 's1' } },
            ['surrounding_service', 'surrounding_all', 'trace', 'session'],
        ],
    ])('%s → %j', (_, overrides, expectedTypes) => {
        const types = getAvailableContexts(makeLog(overrides as any)).map((c) => c.type)
        expect(types).toEqual(expectedTypes)
    })
})

describe('buildContextFilters', () => {
    const timestamp = '2026-03-24T12:00:00.000Z'
    const log = makeLog({
        timestamp,
        resource_attributes: { 'service.name': 'api-server' },
        trace_id: 'trace-abc',
        attributes: { 'session.id': 'sess-123' },
    })

    it.each([
        ['surrounding_service', 1],
        ['surrounding_all', 1],
        ['trace', 5],
        ['session', 30],
    ] as [LogContextType, number][])('%s sets date range with ±%d min window', (contextType, windowMinutes) => {
        const filters = buildContextFilters(log, contextType)
        const from = new Date(filters.dateRange!.date_from!).getTime()
        const to = new Date(filters.dateRange!.date_to!).getTime()
        const center = new Date(timestamp).getTime()
        expect(from).toBe(center - windowMinutes * 60 * 1000)
        expect(to).toBe(center + windowMinutes * 60 * 1000)
    })

    it.each([['surrounding_service'], ['surrounding_all'], ['trace'], ['session']] as [LogContextType][])(
        '%s clears search term and severity levels',
        (contextType) => {
            const filters = buildContextFilters(log, contextType)
            expect(filters.searchTerm).toBe('')
            expect(filters.severityLevels).toEqual([])
        }
    )

    it.each([
        ['surrounding_service', { serviceNames: ['api-server'] }],
        ['surrounding_all', { serviceNames: [] }],
        ['trace', { filterGroup: makeFilterGroup('trace_id', 'trace-abc', PropertyFilterType.Log) }],
        ['session', { filterGroup: makeFilterGroup('session.id', 'sess-123', PropertyFilterType.LogAttribute) }],
    ] as [LogContextType, Record<string, any>][])(
        '%s sets correct context-specific filters',
        (contextType, expected) => {
            const filters = buildContextFilters(log, contextType)
            expect(filters).toEqual(expect.objectContaining(expected))
        }
    )

    it.each([
        ['surrounding_service with no service → empty serviceNames', 'surrounding_service', {}, { serviceNames: [] }],
        ['session with no session_id → undefined filterGroup', 'session', {}, { filterGroup: undefined }],
    ] as [string, LogContextType, Record<string, any>, Record<string, any>][])(
        '%s',
        (_, contextType, overrides, expected) => {
            const filters = buildContextFilters(makeLog({ timestamp, ...overrides }), contextType)
            expect(filters).toEqual(expect.objectContaining(expected))
        }
    )
})
