import { IssueReleasesQueryRow, buildIssueReleaseTimeline, computeReleaseBucketing } from './issueReleases'

const HOUR = 60 * 60

describe('issueReleases', () => {
    it('aligns buckets to the interval and covers the whole range', () => {
        const bucketing = computeReleaseBucketing(
            { date_from: '2024-07-02T00:30:00Z', date_to: '2024-07-09T00:30:00Z' },
            7
        )!
        expect(bucketing.bucketSeconds).toBe(24 * HOUR)
        expect(bucketing.bucketStarts[0]).toBeLessThanOrEqual(bucketing.rangeStart)
        expect(bucketing.bucketStarts[0] % bucketing.bucketSeconds).toBe(0)
        expect(bucketing.bucketStarts.at(-1)! + bucketing.bucketSeconds).toBeGreaterThanOrEqual(bucketing.rangeEnd)
        expect(bucketing.bucketStarts).toHaveLength(8)
    })

    it('returns null for a range that cannot be bucketed', () => {
        expect(computeReleaseBucketing({ date_from: null, date_to: null })).toBeNull()
        expect(
            computeReleaseBucketing({ date_from: '2024-07-09T00:00:00Z', date_to: '2024-07-02T00:00:00Z' })
        ).toBeNull()
    })

    it('orders releases newest first, folds the overflow, and keeps unattributed exceptions apart', () => {
        const bucketStarts = Array.from({ length: 4 }, (_, index) => index * HOUR)
        const bucketing = { bucketSeconds: HOUR, bucketStarts, rangeStart: 0, rangeEnd: 4 * HOUR }
        const rows: IssueReleasesQueryRow[] = [
            [
                'com.example.app',
                '1.0.0',
                '10',
                [
                    [0, 5],
                    [HOUR, 3],
                ],
                8,
                7,
            ],
            ['com.example.app', '1.0.1', '11', [[0, 1]], 1, 7],
            [
                'com.example.app',
                '1.1.0',
                '12',
                [
                    [2 * HOUR, 7],
                    [3 * HOUR, 2],
                ],
                9,
                7,
            ],
            ['com.example.app', '1.0.2', null, [[2 * HOUR, 4]], 4, 7],
            ['com.example.web', '2.0.0', null, [[3 * HOUR, 6]], 6, 7],
            [null, null, null, [[HOUR, 2]], 2, 7],
            ['com.example.app', '0.9.0', '9', [[-HOUR, 100]], 100, 7],
        ]

        const timeline = buildIssueReleaseTimeline(rows, bucketing, 3)

        expect(timeline.groups.map((group) => group.namespace)).toEqual(['com.example.web', 'com.example.app'])
        expect(timeline.groups.flatMap((group) => group.releases.map((release) => release.version))).toEqual([
            '2.0.0',
            '1.1.0',
            '1.0.2',
        ])
        expect(timeline.groups[1].releases[0]).toMatchObject({
            counts: [0, 0, 7, 2],
            total: 9,
            firstSeenIndex: 2,
            lastSeenIndex: 3,
        })
        expect(timeline.other).toMatchObject({ counts: [6, 3, 0, 0], total: 9 })
        expect(timeline.otherReleaseCount).toBe(2)
        expect(timeline.releaseCount).toBe(6)
        expect(timeline.namespaces).toEqual(['com.example.app', 'com.example.web'])
        expect(timeline.unattributed).toMatchObject({ counts: [0, 2, 0, 0], total: 2 })
        expect(timeline.total).toBe(30)
        expect(timeline.maxBucketValue).toBe(7)

        const filtered = buildIssueReleaseTimeline(rows, bucketing, 3, 'com.example.web')
        expect(filtered.groups).toEqual([
            { namespace: 'com.example.web', releases: [expect.objectContaining({ version: '2.0.0' })] },
        ])
        expect(filtered.namespaces).toEqual(['com.example.app', 'com.example.web'])
        expect(filtered.releaseCount).toBe(1)
        expect(filtered.unattributed).toBeNull()
        expect(filtered.total).toBe(6)
    })
})
