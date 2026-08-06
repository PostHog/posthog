import { ErrorTrackingQuery, ProductKey } from '~/queries/schema/schema-general'

import { FilterLogicalOperator, PropertyOperator, UniversalFilterValue } from '../../../frontend/src/types'
import { errorTrackingIssueBreakdownQuery, errorTrackingIssueEventsQuery, errorTrackingQuery } from './queries'

describe('queries', () => {
    describe('errorTrackingQuery', () => {
        describe('usage in web analytics', () => {
            it('should return a query with the correct properties', () => {
                const actual = errorTrackingQuery({
                    orderBy: 'users',
                    dateRange: { date_from: '-7d', date_to: null },
                    filterTestAccounts: true,
                    filterGroup: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [],
                            },
                        ],
                    },
                    columns: ['error', 'users', 'occurrences'],
                    limit: 4,
                    volumeResolution: 20,
                    personId: undefined,
                })
                expect(actual).toMatchSnapshot()
            })
        })

        it('omits a filter the user has not finished writing', () => {
            const actual = errorTrackingQuery({
                orderBy: 'users',
                dateRange: { date_from: '-7d', date_to: null },
                filterTestAccounts: false,
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [
                                { key: 'url', value: null, operator: PropertyOperator.Exact, type: 'event' },
                                {
                                    key: '$browser',
                                    value: ['Chrome'],
                                    operator: PropertyOperator.Exact,
                                    type: 'event',
                                },
                            ] as UniversalFilterValue[],
                        },
                    ],
                },
                columns: ['error', 'users', 'occurrences'],
            })

            expect((actual.source as ErrorTrackingQuery).filterGroup).toEqual({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            { key: '$browser', value: ['Chrome'], operator: PropertyOperator.Exact, type: 'event' },
                        ],
                    },
                ],
            })
        })
    })

    describe('error tracking query tags', () => {
        it('tags issue event queries as error tracking', () => {
            const actual = errorTrackingIssueEventsQuery({
                fingerprints: ['abc'],
                filterTestAccounts: false,
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
                },
                searchQuery: '',
                dateRange: { date_from: '-7d', date_to: null },
                columns: ['*'],
            })

            expect(actual.tags).toEqual({ productKey: ProductKey.ERROR_TRACKING })
        })

        it('escapes quotes in fingerprints and search text', () => {
            const actual = errorTrackingIssueEventsQuery({
                fingerprints: ["fp_with_'quote"],
                filterTestAccounts: false,
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
                },
                searchQuery: "O'Brien",
                dateRange: { date_from: '-7d', date_to: null },
                columns: ['*'],
            })

            const where = (actual.where ?? []).join(' ')
            expect(where).toContain("'fp_with_\\'quote'")
            expect(where).toContain("'%O\\'Brien%'")
        })

        it('tags issue breakdown insight queries as error tracking', () => {
            const actual = errorTrackingIssueBreakdownQuery({
                breakdownProperty: '$browser',
                dateRange: { date_from: '-7d', date_to: null },
                filterTestAccounts: false,
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: FilterLogicalOperator.And,
                            values: [],
                        },
                    ],
                },
                issueId: 'issue-id',
            })

            expect(actual.source.tags).toEqual({ productKey: ProductKey.ERROR_TRACKING })
        })
    })
})
