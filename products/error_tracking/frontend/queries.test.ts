import { ProductKey } from '~/queries/schema/schema-general'

import { FilterLogicalOperator } from '../../../frontend/src/types'
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
    })

    describe('error tracking query tags', () => {
        it('tags issue event queries as error tracking', () => {
            const actual = errorTrackingIssueEventsQuery({
                issueId: '01936e7f-d7ff-7314-b2d4-7627981e34f0',
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

        it('filters issue events by the resolved issue ID and escapes search text', () => {
            const actual = errorTrackingIssueEventsQuery({
                issueId: '01936e7f-d7ff-7314-b2d4-7627981e34f0',
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
            expect(where).toContain("issue_id = toUUID('01936e7f-d7ff-7314-b2d4-7627981e34f0')")
            expect(where).not.toContain('$exception_fingerprint')
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
            expect(actual.source).toMatchObject({
                series: [
                    {
                        properties: [
                            {
                                key: "issue_id = 'issue-id'",
                                type: 'hogql',
                            },
                        ],
                    },
                ],
            })
        })
    })
})
