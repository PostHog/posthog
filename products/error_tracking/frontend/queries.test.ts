import { errorTrackingQuery } from './queries'
import { FilterLogicalOperator } from '../../../frontend/src/types'

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
                    volumeResolution: 0,
                })
                expect(actual).toMatchSnapshot()
            })
        })
    })
})
