import { Dayjs, dayjs } from 'lib/dayjs'

import { ErrorTrackingIssue, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType } from '~/types'

import {
    generateDateRangeLabel,
    getIssueReplayDateRange,
    getIssueReplayFilterGroup,
    mergeIssues,
    sourceDisplay,
} from './utils'

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
            function: '<anonymous>',
            source: 'path/file.py',
        } satisfies ErrorTrackingIssue)
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

describe('getIssueReplayDateRange', () => {
    it('pads a single-occurrence issue so the window is not zero width', () => {
        const seenAt = '2024-01-01T12:00:00.000Z'
        const range = getIssueReplayDateRange(seenAt, dayjs(seenAt))
        expect(range.date_from).toEqual('2024-01-01T11:00:00.000Z')
        expect(range.date_to).toEqual('2024-01-01T13:00:00.000Z')
    })

    it('extends date_from before first_seen to catch sessions that started earlier', () => {
        const firstSeen = '2024-01-01T12:00:00.000Z'
        const lastSeen = dayjs('2024-01-02T12:00:00.000Z')
        const range = getIssueReplayDateRange(firstSeen, lastSeen)
        expect(range.date_from).toEqual('2024-01-01T11:00:00.000Z')
        expect(range.date_to).toEqual('2024-01-02T13:00:00.000Z')
    })

    it('uses the selected event while last_seen is still loading', () => {
        const range = getIssueReplayDateRange('2024-01-01T12:00:00.000Z', null, '2024-04-01T12:00:00.000Z')
        expect(range.date_to).toEqual('2024-04-01T13:00:00.000Z')
    })

    it('uses a selected event that is newer than a stale last_seen', () => {
        const range = getIssueReplayDateRange(
            '2024-01-01T12:00:00.000Z',
            dayjs('2024-02-01T12:00:00.000Z'),
            '2024-04-01T12:00:00.000Z'
        )
        expect(range.date_to).toEqual('2024-04-01T13:00:00.000Z')
    })

    it('falls back to first_seen when no later timestamp is known', () => {
        const firstSeen = '2024-01-01T12:00:00.000Z'
        expect(getIssueReplayDateRange(firstSeen, null).date_to).toEqual('2024-01-01T13:00:00.000Z')
        expect(getIssueReplayDateRange(firstSeen, dayjs('2023-12-31T00:00:00.000Z')).date_to).toEqual(
            '2024-01-01T13:00:00.000Z'
        )
    })

    // first_seen is null for an issue with no ingested events — reachable via the
    // metrics error-spike overlay, and it used to crash the issue scene render.
    it('anchors on last_seen when first_seen is missing', () => {
        const range = getIssueReplayDateRange(null, dayjs('2024-01-02T12:00:00.000Z'))
        expect(range.date_from).toEqual('2024-01-02T11:00:00.000Z')
        expect(range.date_to).toEqual('2024-01-02T13:00:00.000Z')
    })

    it('anchors on the selected event when first_seen and last_seen are missing', () => {
        const range = getIssueReplayDateRange(null, null, '2024-04-01T12:00:00.000Z')
        expect(range.date_from).toEqual('2024-04-01T11:00:00.000Z')
        expect(range.date_to).toEqual('2024-04-01T13:00:00.000Z')
        expect(() => getIssueReplayDateRange(null, null)).not.toThrow()
    })
})

describe('getIssueReplayFilterGroup', () => {
    it('scopes the merge-aware issue field to exception events', () => {
        expect(getIssueReplayFilterGroup("issue-'quoted'")).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            id: '$exception',
                            name: '$exception',
                            type: 'events',
                            properties: [
                                {
                                    key: "issue_id = 'issue-\\'quoted\\''",
                                    type: PropertyFilterType.HogQL,
                                },
                            ],
                        },
                    ],
                },
            ],
        })
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
