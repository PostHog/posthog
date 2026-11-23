import { type BucketedFacetRow, buildShareSeries, isMostlyLabeled } from './leaderboardShares'

const row = (bucket: string, label: string, calls: number): BucketedFacetRow => ({ bucket, label, calls })

describe('leaderboardShares', () => {
    it('groups per bucket, drops null groups and folds the tail into a final Other series', () => {
        const rows = [
            row('d1', 'a', 5),
            row('d2', 'a', 5),
            row('d1', 'b', 3),
            row('d1', 'c', 1),
            row('d2', 'd', 1),
            row('d1', 'Unknown', 50),
            row('d9', 'a', 99),
        ]
        const series = buildShareSeries(rows, ['d1', 'd2'], (label) => (label === 'Unknown' ? null : label), 2)
        expect(series).toEqual([
            { label: 'a', data: [5, 5] },
            { label: 'b', data: [3, 0] },
            { label: 'Other', data: [1, 1] },
        ])
    })

    test.each([
        ['every call is Unknown', [row('d1', 'Unknown', 4)], true],
        ['Unknown reaches the threshold', [row('d1', 'Unknown', 9), row('d2', 'oauth', 1)], true],
        ['Unknown falls short of the threshold', [row('d1', 'Unknown', 8), row('d2', 'oauth', 2)], false],
        ['there are no calls', [], false],
    ])('isMostlyLabeled when %s', (_name, rows, expected) => {
        expect(isMostlyLabeled(rows, ['Unknown'])).toEqual(expected)
    })
})
