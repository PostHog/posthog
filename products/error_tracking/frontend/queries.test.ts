import { dayjs } from 'lib/dayjs'

import { generateSparklineLabels } from './utils'
import { errorTrackingQuery } from './queries'
import { FilterLogicalOperator } from '../../../frontend/src/types'

function getSparklineLabels(timeAgo: string, resolution: number): string[] {
    const dateRange = { date_from: timeAgo }
    return generateSparklineLabels(dateRange, resolution).map((label) => {
        return dayjs(label).format('D MMM, YYYY HH:mm (UTC)')
    })
}

describe('queries', () => {
    describe('generateSparklineProps', () => {
        beforeAll(() => {
            jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
        })

        it('resolution', async () => {
            new Array(5)
                .fill(0)
                .map((_, idx) => idx)
                .map((value) => getSparklineLabels(`-${value}h`, 10))
                .map((labels) => expect(labels.length).toEqual(10))
        })

        it('1h', async () => {
            const labels = getSparklineLabels('-1h', 4)
            expect(labels).toEqual([
                '10 Jan, 2023 16:22 (UTC)',
                '10 Jan, 2023 16:37 (UTC)',
                '10 Jan, 2023 16:52 (UTC)',
                '10 Jan, 2023 17:07 (UTC)',
            ])
        })

        it('24h', async () => {
            const labels = getSparklineLabels('-24h', 4)
            expect(labels).toEqual([
                '9 Jan, 2023 17:22 (UTC)',
                '9 Jan, 2023 23:22 (UTC)',
                '10 Jan, 2023 05:22 (UTC)',
                '10 Jan, 2023 11:22 (UTC)',
            ])
        })

        it('7d', async () => {
            const labels = getSparklineLabels('-7d', 4)
            expect(labels).toEqual([
                '3 Jan, 2023 17:22 (UTC)',
                '5 Jan, 2023 11:22 (UTC)',
                '7 Jan, 2023 05:22 (UTC)',
                '8 Jan, 2023 23:22 (UTC)',
            ])
        })

        it('14d', async () => {
            const labels = getSparklineLabels('-14d', 4)
            expect(labels).toEqual([
                '27 Dec, 2022 17:22 (UTC)',
                '31 Dec, 2022 05:22 (UTC)',
                '3 Jan, 2023 17:22 (UTC)',
                '7 Jan, 2023 05:22 (UTC)',
            ])
        })

        it('mStart', async () => {
            const labels = getSparklineLabels('-mStart', 10)
            expect(labels).toEqual([
                '1 Jan, 2023 00:00 (UTC)',
                '1 Jan, 2023 23:20 (UTC)',
                '2 Jan, 2023 22:40 (UTC)',
                '3 Jan, 2023 22:00 (UTC)',
                '4 Jan, 2023 21:20 (UTC)',
                '5 Jan, 2023 20:41 (UTC)',
                '6 Jan, 2023 20:01 (UTC)',
                '7 Jan, 2023 19:21 (UTC)',
                '8 Jan, 2023 18:41 (UTC)',
                '9 Jan, 2023 18:01 (UTC)',
            ])
        })

        it('yStart', async () => {
            const labels = getSparklineLabels('yStart', 4)
            expect(labels).toEqual([
                '1 Jan, 2023 00:00 (UTC)',
                '3 Jan, 2023 10:20 (UTC)',
                '5 Jan, 2023 20:41 (UTC)',
                '8 Jan, 2023 07:01 (UTC)',
            ])
        })
    })

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
                })
                expect(actual).toMatchSnapshot()
            })
        })
    })
})
