import { Dayjs, dayjs } from 'lib/dayjs'

import {
    generateDateRangeLabel,
    generateSparklineLabels,
    mergeIssues,
    resolveDate,
    resolveDateRange,
    sourceDisplay,
} from './utils'
import { ErrorTrackingIssue, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { generateDateRangeLabel, mergeIssues } from './utils'

function wrapVolumeBuckets(
    initialDate: Dayjs,
    volumeBuckets: number[]
): ErrorTrackingIssueAggregations['volume_buckets'] {
    return volumeBuckets.map((v, index) => ({
        value: v,
        label: initialDate.add(index, 'day').format('YYYY-MM-DD'),
    }))
}

describe('mergeIssues', () => {
    it('arbitrary values', async () => {
        const initialDate = dayjs().startOf('day')
        const primaryIssue: ErrorTrackingIssue = {
            id: 'primaryId',
            assignee: { type: 'user', id: 400 },
            description: 'This is the original description',
            name: 'TypeError',
            first_seen: '2024-07-22T13:15:07.074000Z',
            last_seen: '2024-07-20T13:15:50.186000Z',
            aggregations: {
                occurrences: 250,
                sessions: 100,
                users: 50,
                volume_buckets: wrapVolumeBuckets(initialDate, [0, 0, 10, 25, 95]),
            },
            library: 'web',
            status: 'active',
            earliest: '',
            function: '<anonymous>',
            source: 'path/file.py',
            external_issues: [],
        }

        const mergingIssues: ErrorTrackingIssue[] = [
            {
                id: 'secondId',
                assignee: { type: 'user', id: 100 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-20T13:15:50.186000Z',
                aggregations: {
                    occurrences: 10,
                    sessions: 5,
                    users: 1,
                    volume_buckets: wrapVolumeBuckets(initialDate, [0, 0, 0, 0, 1]),
                },
                library: 'web',
                status: 'active',
                external_issues: [],
            },
            {
                id: 'thirdId',
                assignee: { type: 'user', id: 400 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                aggregations: {
                    occurrences: 1,
                    sessions: 1,
                    users: 1,
                    volume_buckets: wrapVolumeBuckets(initialDate, [0, 0, 0, 1, 0]),
                },
                library: 'web',
                status: 'active',
                external_issues: [],
            },
            {
                id: 'fourthId',
                assignee: null,
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2023-07-22T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                aggregations: {
                    occurrences: 1000,
                    sessions: 500,
                    users: 50,
                    volume_buckets: wrapVolumeBuckets(initialDate, [0, 500, 1500, 1000, 1310]),
                },
                library: 'web',
                status: 'active',
                external_issues: [],
            },
        ]

        const mergedIssue = mergeIssues(primaryIssue, mergingIssues)

        expect(mergedIssue).toEqual({
            // retains values from primary group
            id: 'primaryId',
            assignee: { type: 'user', id: 400 },
            description: 'This is the original description',
            name: 'TypeError',
            status: 'active',
            // earliest first_seen
            first_seen: '2023-07-22T13:15:07.074Z',
            // latest last_seen
            last_seen: '2024-07-22T13:15:50.186Z',
            external_issues: [],
            library: 'web',
            aggregations: {
                // sums counts
                occurrences: 1261,
                sessions: 606,
                users: 102,
                volume_buckets: wrapVolumeBuckets(initialDate, [0, 500, 1510, 1026, 1406]),
            },
<<<<<<< HEAD:frontend/src/scenes/error-tracking/utils.test.ts
            function: '<anonymous>',
            source: 'path/file.py',
        })
=======
        } satisfies ErrorTrackingIssue)
>>>>>>> master:products/error_tracking/frontend/utils.test.ts
    })
})

describe('generate sparkline labels', () => {
    beforeAll(() => {
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    it('test date range label generation', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-7d',
        })
        expect(rangeLabel).toEqual('7d')
    })
})

describe('date range label generation', () => {
    it('-7d', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-7d',
        })
        expect(rangeLabel).toEqual('7d')
    })

    it('-24h', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-24h',
        })
        expect(rangeLabel).toEqual('24h')
    })

    it('-3h', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-3h',
        })
        expect(rangeLabel).toEqual('3h')
    })

    it('01-01-2025', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '01-01-2025',
        })
        expect(rangeLabel).toEqual('Custom')
    })

    it('yStart', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: 'yStart',
        })
        expect(rangeLabel).toEqual('Year')
    })

    it('mStart', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: 'mStart',
        })
        expect(rangeLabel).toEqual('Month')
    })
})

describe('sourceDisplay', () => {
    it('nicely formats paths', async () => {
        expect(sourceDisplay('')).toEqual('')
        expect(sourceDisplay('kea/lib/index.cjs.js')).toEqual('kea.lib.index')
        expect(
            sourceDisplay('../../node_modules/.pnpm/reselect@4.1.7/node_modules/reselect/lib/defaultMemoize.js')
        ).toEqual('reselect.lib.defaultMemoize')
        expect(
            sourceDisplay(
                '../../node_modules/.pnpm/kea-loaders@3.0.0_kea@3.1.5_react@18.2.0_/node_modules/kea-loaders/src/index.ts'
            )
        ).toEqual('kea-loaders.src.index')
    })
})
