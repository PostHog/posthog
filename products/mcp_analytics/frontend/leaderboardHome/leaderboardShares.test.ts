import {
    type BucketedFacetRow,
    buildLabShares,
    buildShareSeries,
    hasKnownLabels,
    modelLab,
    topFacetRows,
    type WindowFacetRow,
} from './leaderboardShares'

const row = (bucket: string, label: string, calls: number): BucketedFacetRow => ({ bucket, label, calls })
const windowRow = (label: string, calls: number): WindowFacetRow => ({ label, calls, users: 1, errors: 0 })

describe('leaderboardShares', () => {
    test.each([
        ['claude-opus-4-5', 'Anthropic'],
        ['gpt-5-codex', 'OpenAI'],
        ['gpt-oss-120b', 'Open weights'],
        ['gemini-2.5-pro', 'Google'],
        ['grok-4', 'xAI'],
        ['composer-1', 'Cursor'],
        ['some-new-model', 'Other'],
    ])('modelLab(%s) is %s', (model, lab) => {
        expect(modelLab(model)).toEqual(lab)
    })

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

    it('computes lab shares from named models only and leaves out the Other lab', () => {
        const shares = buildLabShares([
            row('d1', 'claude-sonnet-4', 6),
            row('d2', 'claude-opus-4', 2),
            row('d1', 'gpt-5', 2),
            row('d1', 'Unknown', 100),
            row('d1', 'mystery', 10),
        ])
        expect(shares).toEqual([
            { lab: 'Anthropic', calls: 8, share: 40 },
            { lab: 'OpenAI', calls: 2, share: 10 },
        ])
    })

    it('puts Unknown last and folds rows past the limit into Other', () => {
        const rows = [
            windowRow('Unknown', 90),
            windowRow('a', 1),
            windowRow('b', 5),
            windowRow('c', 3),
            windowRow('Other', 2),
        ]
        expect(topFacetRows(rows, 2).map((r) => [r.label, r.calls])).toEqual([
            ['b', 5],
            ['c', 3],
            ['Other', 3],
            ['Unknown', 90],
        ])
    })

    test.each([
        [[windowRow('Unknown', 4)], false],
        [[windowRow('Unknown', 4), windowRow('oauth', 1)], true],
        [[], false],
    ])('hasKnownLabels(%j) is %s', (rows, expected) => {
        expect(hasKnownLabels(rows)).toEqual(expected)
    })
})
