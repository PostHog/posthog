import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    FilterIdentifier,
    PersonData,
    createPersonFilter,
    getFilterIdentifier,
    getTracesUrlWithPersonFilter,
} from './llmAnalyticsColumnRenderers'

describe('llmAnalyticsColumnRenderers', () => {
    describe('getFilterIdentifier', () => {
        it.each<[string, PersonData | null | undefined, FilterIdentifier | null]>([
            ['returns null when person is null', null, null],
            ['returns null when person is undefined', undefined, null],
            [
                'returns null when person has no identifiable properties',
                { distinct_id: undefined, properties: {} },
                null,
            ],
            [
                'returns email when person has email property',
                { distinct_id: 'user-123', properties: { email: 'test@example.com', username: 'testuser' } },
                { type: 'email', value: 'test@example.com' },
            ],
            [
                'returns username when person has username but no email',
                { distinct_id: 'user-123', properties: { username: 'testuser' } },
                { type: 'username', value: 'testuser' },
            ],
            [
                'returns distinct_id when person has only distinct_id',
                { distinct_id: 'user-123', properties: {} },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'returns distinct_id when properties is undefined',
                { distinct_id: 'user-123' },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'prioritizes email over username and distinct_id',
                { distinct_id: 'user-123', properties: { email: 'test@example.com', username: 'testuser' } },
                { type: 'email', value: 'test@example.com' },
            ],
            [
                'prioritizes username over distinct_id when no email',
                { distinct_id: 'user-123', properties: { username: 'testuser' } },
                { type: 'username', value: 'testuser' },
            ],
            [
                'ignores non-string email property',
                { distinct_id: 'user-123', properties: { email: 123 } },
                { type: 'distinct_id', value: 'user-123' },
            ],
            [
                'ignores non-string username property',
                { distinct_id: 'user-123', properties: { username: ['array'] } },
                { type: 'distinct_id', value: 'user-123' },
            ],
        ])('%s', (_description, person, expected) => {
            expect(getFilterIdentifier(person)).toEqual(expected)
        })
    })

    describe('createPersonFilter', () => {
        it.each<[string, FilterIdentifier, ReturnType<typeof createPersonFilter>]>([
            [
                'creates HogQL filter for distinct_id type',
                { type: 'distinct_id', value: 'user-123' },
                { type: PropertyFilterType.HogQL, key: "distinct_id == 'user-123'" },
            ],
            [
                'creates Person property filter for email type',
                { type: 'email', value: 'test@example.com' },
                {
                    type: PropertyFilterType.Person,
                    key: 'email',
                    operator: PropertyOperator.Exact,
                    value: 'test@example.com',
                },
            ],
            [
                'creates Person property filter for username type',
                { type: 'username', value: 'testuser' },
                {
                    type: PropertyFilterType.Person,
                    key: 'username',
                    operator: PropertyOperator.Exact,
                    value: 'testuser',
                },
            ],
        ])('%s', (_description, filterIdentifier, expected) => {
            expect(createPersonFilter(filterIdentifier)).toEqual(expected)
        })
    })

    describe('getTracesUrlWithPersonFilter', () => {
        it('generates URL with email filter', () => {
            const url = getTracesUrlWithPersonFilter({ type: 'email', value: 'test@example.com' })

            expect(url).toContain('/llm-analytics/traces')
            expect(url).toContain('filters')
            expect(url).toContain('email')
            expect(url).toContain('test%40example.com')
        })

        it('generates URL with distinct_id filter', () => {
            const url = getTracesUrlWithPersonFilter({ type: 'distinct_id', value: 'user-123' })

            expect(url).toContain('/llm-analytics/traces')
            expect(url).toContain('filters')
            expect(url).toContain("distinct_id%20%3D%3D%20'user-123'")
        })

        it('includes date range params when provided', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: '2024-01-01', dateTo: '2024-01-31' }
            )

            expect(url).toContain('date_from=2024-01-01')
            expect(url).toContain('date_to=2024-01-31')
        })

        it('omits date params when they are null', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: null, dateTo: null }
            )

            expect(url).not.toContain('date_from')
            expect(url).not.toContain('date_to')
        })

        it('handles partial date range', () => {
            const url = getTracesUrlWithPersonFilter(
                { type: 'email', value: 'test@example.com' },
                { dateFrom: '2024-01-01', dateTo: null }
            )

            expect(url).toContain('date_from=2024-01-01')
            expect(url).not.toContain('date_to')
        })
    })
})
