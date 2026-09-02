import { UniversalFiltersGroup } from '~/types'

import { DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS } from 'products/logs/frontend/logsConfigLogic'

import {
    buildLogsSessionFilters,
    formatFilterGroupValues,
    getFiltersSummaryLines,
    getSessionIdFromLogAttributes,
    isDistinctIdKey,
    isSessionIdKey,
} from './utils'

jest.mock('lib/components/DateFilter/DateRangePicker/utils', () => ({
    formatDateRangeLabel: () => '-1h \u2192 now',
}))

describe('logs utils', () => {
    describe.each([
        // Exact matches
        ['distinct.id', true],
        ['distinct_id', true],
        ['distinctId', true],
        ['distinctID', true],
        ['posthogDistinctId', true],
        ['posthogDistinctID', true],
        ['posthog_distinct_id', true],
        ['posthog.distinct.id', true],
        ['posthog.distinct_id', true],
        // Dotted paths
        ['foo.distinct_id', true],
        ['foo.bar.posthogDistinctId', true],
        ['foo.bar.posthog_distinct_id', true],
        ['foo.bar.distinct_id', true],
        ['foo.bar.distinct.id', true],
        ['resource.attributes.distinct_id', true],
        // Non-matches
        ['not_distinct_id_at_all', false],
        ['distinct_id.something', false],
        ['xdistinct_id', false],
        ['', false],
    ])('isDistinctIdKey(%s)', (key, expected) => {
        it(`returns ${expected}`, () => {
            expect(isDistinctIdKey(key)).toBe(expected)
        })
    })

    describe('isDistinctIdKey with configured keys', () => {
        it('matches a configured key exactly, without dot-suffix expansion', () => {
            expect(isDistinctIdKey('user.id', ['user.id'])).toBe(true)
            expect(isDistinctIdKey('prefixed.user.id', ['user.id'])).toBe(false)
        })

        it('keeps matching the built-in conventions alongside configured keys', () => {
            expect(isDistinctIdKey('posthogDistinctId', ['user.id'])).toBe(true)
            expect(isDistinctIdKey('unrelated', ['user.id'])).toBe(false)
        })
    })

    describe.each([
        // Exact matches
        ['session.id', true],
        ['session_id', true],
        ['sessionId', true],
        ['sessionID', true],
        ['$session_id', true],
        ['posthogSessionId', true],
        ['posthogSessionID', true],
        ['posthog_session_id', true],
        ['posthog.session.id', true],
        ['posthog.session_id', true],
        // Dotted paths
        ['foo.session_id', true],
        ['foo.bar.posthogSessionId', true],
        ['foo.bar.posthog_session_id', true],
        ['foo.bar.session_id', true],
        ['foo.bar.session.id', true],
        ['resource.attributes.$session_id', true],
        // Non-matches
        ['not_session_id_at_all', false],
        ['session_id.something', false],
        ['xsession_id', false],
        ['', false],
    ])('isSessionIdKey(%s)', (key, expected) => {
        it(`returns ${expected}`, () => {
            expect(isSessionIdKey(key)).toBe(expected)
        })
    })

    describe.each([
        ['from attributes', { session_id: 'abc123' }, undefined, 'abc123'],
        ['from resource_attributes', undefined, { session_id: 'xyz789' }, 'xyz789'],
        ['attributes takes precedence', { session_id: 'from-attr' }, { session_id: 'from-resource' }, 'from-attr'],
        ['nested key in attributes', { 'foo.session_id': 'nested' }, undefined, 'nested'],
        ['$session_id variant', { $session_id: 'dollar-sign' }, undefined, 'dollar-sign'],
        ['no session id', { other_key: 'value' }, { another_key: 'value' }, null],
        ['empty objects', {}, {}, null],
        ['undefined inputs', undefined, undefined, null],
        ['ignores falsy values', { session_id: '' }, { session_id: 'fallback' }, 'fallback'],
        ['ignores null values', { session_id: null }, { session_id: 'fallback' }, 'fallback'],
        ['converts number to string', { session_id: 12345 }, undefined, '12345'],
    ])('getSessionIdFromLogAttributes - %s', (_, attributes, resourceAttributes, expected) => {
        it(`returns ${expected}`, () => {
            expect(
                getSessionIdFromLogAttributes(
                    attributes as Record<string, unknown> | undefined,
                    resourceAttributes as Record<string, unknown> | undefined
                )
            ).toBe(expected)
        })
    })

    describe('configured session ID keys', () => {
        it.each([
            [
                'configured key wins over a built-in convention key',
                ['my.custom.key'],
                { session_id: 'builtin', 'my.custom.key': 'custom' },
                undefined,
                'custom',
            ],
            [
                'configured keys are checked in list order',
                ['second.key', 'first.key'],
                { 'first.key': 'first', 'second.key': 'second' },
                undefined,
                'second',
            ],
            [
                'configured key found in resource_attributes',
                ['my.custom.key'],
                undefined,
                { 'my.custom.key': 'from-resource' },
                'from-resource',
            ],
            [
                'falls back to built-in conventions when configured keys are absent',
                ['my.custom.key'],
                { $session_id: 'builtin' },
                undefined,
                'builtin',
            ],
            [
                'configured keys match exactly, not by dot suffix',
                ['custom.key'],
                { 'prefix.custom.key': 'suffixed' },
                undefined,
                null,
            ],
        ])('%s', (_, configuredKeys, attributes, resourceAttributes, expected) => {
            expect(
                getSessionIdFromLogAttributes(
                    attributes as Record<string, unknown> | undefined,
                    resourceAttributes as Record<string, unknown> | undefined,
                    configuredKeys
                )
            ).toBe(expected)
        })

        it.each([
            ['my.custom.key', ['my.custom.key'], true],
            ['prefix.my.custom.key', ['my.custom.key'], false],
        ])('isSessionIdKey(%s, %j) returns %s', (key, configuredKeys, expected) => {
            expect(isSessionIdKey(key, configuredKeys)).toBe(expected)
        })
    })

    describe('buildLogsSessionFilters', () => {
        // Byte-for-byte SESSION_ID_KEYS from utils.tsx. Spelled out rather than imported so a
        // silent edit to that list shows up here as a failing assertion.
        const CONVENTION_KEYS = [
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

        // Keys of the log-attribute filters only. Every key also gets a resource-attribute
        // twin, asserted separately below.
        const filterKeys = (configuredKeys?: string[]): string[] => {
            const innerGroup = buildLogsSessionFilters('sess-1', configuredKeys).filterGroup!
                .values[0] as UniversalFiltersGroup
            expect(innerGroup.type).toBe('OR')
            return (innerGroup.values as { key: string; type: string }[])
                .filter((filter) => filter.type === 'log_attribute')
                .map((filter) => filter.key)
        }

        it.each([
            ['no configured keys', undefined],
            ['empty configured list', []],
        ])('%s queries the built-in conventions', (_, configuredKeys) => {
            expect(filterKeys(configuredKeys)).toEqual(CONVENTION_KEYS)
        })

        it('puts configured keys first, then the conventions, deduped', () => {
            // `sessionId` is configured and a convention: it keeps its configured position
            // and is not repeated.
            expect(filterKeys(['custom.key', 'sessionId'])).toEqual([
                'custom.key',
                'sessionId',
                ...CONVENTION_KEYS.filter((key) => key !== 'sessionId'),
            ])
        })

        it('queries the shipped default, which must be one of the conventions', () => {
            // buildLogsSessionFilters queries the conventions, not the default, so a default
            // outside this list would go unqueried for a team that never edited it.
            expect(CONVENTION_KEYS).toEqual(expect.arrayContaining(DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS))
        })

        it('queries sessionId for a team whose stored config is the old posthogSessionId default', () => {
            // Every team created before the default changed has `posthogSessionId` materialised.
            // The conventions union is what keeps their session link resolving SDK logs.
            expect(filterKeys(['posthogSessionId'])).toContain('sessionId')
        })

        it('queries each key as both a log attribute and a resource attribute', () => {
            // A log carrying the session id only under resource_attributes still renders the
            // session link, so View Logs has to match that map too.
            const filters = buildLogsSessionFilters('sess-1', ['custom.key'])

            const innerGroup = filters.filterGroup!.values[0] as UniversalFiltersGroup
            expect(innerGroup.values.slice(0, 2)).toEqual([
                { key: 'custom.key', value: ['sess-1'], operator: 'exact', type: 'log_attribute' },
                { key: 'custom.key', value: ['sess-1'], operator: 'exact', type: 'log_resource_attribute' },
            ])
            expect(filters.dateRange).toBeUndefined()
        })

        it('pairs every queried key across both maps', () => {
            const innerGroup = buildLogsSessionFilters('sess-1', ['custom.key']).filterGroup!
                .values[0] as UniversalFiltersGroup
            const values = innerGroup.values as { key: string; type: string }[]
            const keysByType = (type: string): string[] =>
                values.filter((filter) => filter.type === type).map((filter) => filter.key)

            expect(keysByType('log_resource_attribute')).toEqual(keysByType('log_attribute'))
        })

        it('scopes the date range around the timestamp', () => {
            const filters = buildLogsSessionFilters('sess-1', undefined, '2026-03-24T12:00:00.000Z')
            expect(filters.dateRange).toEqual({
                date_from: '2026-03-24T11:30:00.000Z',
                date_to: '2026-03-24T12:30:00.000Z',
            })
        })
    })

    const filterGroup = (
        ...filters: Array<{ key: string; value: any; type?: string; operator?: string }>
    ): Record<string, any> => ({
        type: 'AND',
        values: [{ type: 'AND', values: filters.map((f) => ({ type: 'log_entry', operator: 'exact', ...f })) }],
    })

    describe.each([
        ['undefined input', undefined, []],
        ['empty group', { type: 'AND', values: [] }, []],
        [
            'simple property filters',
            filterGroup({ key: 'env', value: 'production' }, { key: 'region', value: 'us-east' }),
            ['env=production', 'region=us-east'],
        ],
        [
            'truncates long values',
            filterGroup({ key: 'msg', value: 'this is a very long value that exceeds limit' }),
            ['msg=this is a very ...'],
        ],
        ['joins array values', filterGroup({ key: 'env', value: ['prod', 'staging'] }), ['env=prod, staging']],
    ])('formatFilterGroupValues – %s', (_, input, expected) => {
        it(`returns expected output`, () => {
            expect(formatFilterGroupValues(input as Record<string, any> | undefined)).toEqual(expected)
        })
    })

    describe.each([
        ['empty filters', {}, []],
        [
            'date range',
            { dateRange: { date_from: '-1h', date_to: null } },
            [{ label: 'Date range', value: expect.any(String) }],
        ],
        [
            'severity levels capitalized',
            { severityLevels: ['error', 'fatal'] },
            [{ label: 'Severity', value: 'Error, Fatal' }],
        ],
        ['singular service', { serviceNames: ['api'] }, [{ label: 'Service', value: 'api' }]],
        // A viewer-written selection lives in the group, so an entry holding it has to summarize the
        // same way one holding a dedicated field does.
        [
            'group-stored level and service selections',
            {
                filterGroup: filterGroup(
                    { key: 'severity_level', value: ['error'], type: 'log' },
                    { key: 'service_name', value: ['api'], type: 'log' }
                ),
            },
            [
                { label: 'Severity', value: 'Error' },
                { label: 'Service', value: 'api' },
            ],
        ],
        [
            'a group-stored exclusion still shows as a filter',
            {
                filterGroup: filterGroup({
                    key: 'service_name',
                    value: ['api'],
                    type: 'log',
                    operator: 'is_not',
                }),
            },
            [{ label: 'Filter', value: 'service_name=api' }],
        ],
        [
            'plural services with truncation',
            { serviceNames: ['api', 'worker', 'scheduler', 'cron'] },
            [{ label: 'Services', value: 'api, worker, scheduler +1 more' }],
        ],
        ['short search term', { searchTerm: 'timeout' }, [{ label: 'Search', value: '"timeout"' }]],
        [
            'long search term truncated',
            { searchTerm: 'a'.repeat(40) },
            [{ label: 'Search', value: `"${'a'.repeat(30)}..."` }],
        ],
        [
            'single attribute filter',
            { filterGroup: filterGroup({ key: 'env', value: 'prod' }) },
            [{ label: 'Filter', value: 'env=prod' }],
        ],
        [
            'multiple attribute filters',
            { filterGroup: filterGroup({ key: 'env', value: 'prod' }, { key: 'region', value: 'us' }) },
            [{ label: 'Filters', value: 'env=prod, region=us' }],
        ],
    ])('getFiltersSummaryLines – %s', (_, filters, expected) => {
        it(`returns expected output`, () => {
            expect(getFiltersSummaryLines(filters as Record<string, any>)).toEqual(expected)
        })
    })

    it('getFiltersSummaryLines combines all filter types', () => {
        const lines = getFiltersSummaryLines({
            dateRange: { date_from: '-1h', date_to: null },
            severityLevels: ['error'],
            serviceNames: ['api'],
            searchTerm: 'timeout',
        })
        expect(lines).toHaveLength(4)
        expect(lines.map((l) => l.label)).toEqual(['Date range', 'Severity', 'Service', 'Search'])
    })
})
