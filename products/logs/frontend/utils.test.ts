import {
    formatFilterGroupValues,
    getFiltersSummaryLines,
    getSessionIdFromLogAttributes,
    isDistinctIdKey,
    isSessionIdKey,
} from './utils'

jest.mock('products/logs/frontend/components/LogsViewer/Filters/LogsDateRangePicker/utils', () => ({
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
