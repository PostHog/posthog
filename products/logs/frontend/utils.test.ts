import { UniversalFiltersGroup } from '~/types'

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
        it.each([
            ['defaults to the SDK convention key', undefined, ['posthogSessionId']],
            ['uses configured keys in order', ['session.id', 'custom.key'], ['session.id', 'custom.key']],
            ['empty configured list falls back to default', [], ['posthogSessionId']],
        ])('%s', (_, configuredKeys, expectedKeys) => {
            const filters = buildLogsSessionFilters('sess-1', configuredKeys)

            const innerGroup = filters.filterGroup!.values[0] as UniversalFiltersGroup
            expect(innerGroup.type).toBe('OR')
            expect(innerGroup.values).toEqual(
                expectedKeys.map((key) => ({
                    key,
                    value: ['sess-1'],
                    operator: 'exact',
                    type: 'log_attribute',
                }))
            )
            expect(filters.dateRange).toBeUndefined()
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
