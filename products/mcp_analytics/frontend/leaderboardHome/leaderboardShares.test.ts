import { modelRowLabels } from '../aiLabs'
import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import {
    type BucketedFacetRow,
    type LabShare,
    buildLabShares,
    buildLabUserShares,
    buildModelShareSeries,
    buildReliabilitySeries,
    harnessErrorRateRows,
    buildShareSeries,
    hasKnownLabels,
    leadingLabs,
    modelRowsFromBuckets,
    toReliabilityRows,
    topFacetRows,
    type ReliabilityRow,
    type WindowFacetRow,
} from './leaderboardShares'

const row = (bucket: string, label: string, calls: number): BucketedFacetRow => ({ bucket, label, calls })
const labShare = (lab: LabShare['lab'], share: number): LabShare => ({ lab, share, count: share, total: 100 })
const windowRow = (label: string, calls: number): WindowFacetRow => ({ label, calls, users: 1, errors: 0 })

describe('leaderboardShares', () => {
    it('names the top models and lone leftovers, folds the rest per lab, and orders series by lab', () => {
        const rows = [
            row('d1', 'gpt-6', 50),
            row('d1', 'claude-opus-5-5', 40),
            row('d1', 'claude-haiku-5', 5),
            row('d1', 'claude-opus-4-8', 2),
            row('d1', 'gpt-5', 4),
            row('d1', 'grok-4.7', 3),
            row('d1', 'example-custom-model', 2),
            row('d1', 'Other', 1),
            row('d1', 'Unknown', 99),
        ]
        const rowLabels = modelRowLabels(
            rows.map((row) => row.label).filter((label) => label !== 'Unknown'),
            new Set(['gpt-6', 'claude-opus-5-5'])
        )
        expect(buildModelShareSeries(rows, ['d1'], rowLabels)).toEqual([
            { label: 'claude-opus-5-5', data: [40] },
            { label: 'Other Anthropic models', data: [7] },
            { label: 'gpt-6', data: [50] },
            { label: 'gpt-5', data: [4] },
            { label: 'grok-4.7', data: [3] },
            { label: 'Other models', data: [3] },
        ])
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

    it('uses model names to break ties between model series in one lab', () => {
        const rows = [row('d1', 'claude-sonnet', 1), row('d1', 'claude-opus', 1)]
        const rowLabels = modelRowLabels(
            rows.map(({ label }) => label),
            new Set(rows.map(({ label }) => label))
        )

        expect(buildModelShareSeries(rows, ['d1'], rowLabels).map(({ label }) => label)).toEqual([
            'claude-opus',
            'claude-sonnet',
        ])
    })

    it('builds model totals from the same bucketed rows as the time chart', () => {
        expect(
            modelRowsFromBuckets([row('d1', 'claude-sonnet', 2), row('d2', 'claude-sonnet', 3), row('d2', 'gpt-6', 4)])
        ).toEqual([
            { model: 'claude-sonnet', total_calls: 5 },
            { model: 'gpt-6', total_calls: 4 },
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
            { lab: 'Anthropic', share: 40, count: 8, total: 20 },
            { lab: 'OpenAI', share: 10, count: 2, total: 20 },
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
        expect(topFacetRows(rows, 2).map((r) => [r.label, r.calls, r.users])).toEqual([
            ['b', 5, 1],
            ['c', 3, 1],
            ['Other', 3, null],
            ['Unknown', 90, 1],
        ])
    })

    it('computes lab user shares against users with a named model, so they can pass 100 in total', () => {
        const shares = buildLabUserShares(
            [
                { lab: 'OpenAI', users: 6 },
                { lab: 'Anthropic', users: 9 },
                { lab: 'Unknown', users: 40 },
                { lab: 'Other', users: 3 },
            ],
            10
        )
        expect(shares).toEqual([
            { lab: 'Anthropic', share: 90, count: 9, total: 10 },
            { lab: 'OpenAI', share: 60, count: 6, total: 10 },
        ])
    })

    it('keeps the most used harnesses for the error rate chart and leaves out Other', () => {
        const harness = (category: string, total_calls: number): HarnessRow => ({
            category,
            total_calls,
            errors: 1,
            error_rate_pct: 1,
            sessions: 1,
        })
        const rows = [harness('Other', 1000), ...Array.from({ length: 9 }, (_, i) => harness(`h${i}`, 100 - i))]
        const kept = harnessErrorRateRows(rows).map((row) => row.tool)
        expect(kept).toEqual(['h0', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7'])
    })

    test.each([
        [[windowRow('Unknown', 4)], false],
        [[windowRow('Unknown', 4), windowRow('oauth', 1)], true],
        [[], false],
    ])('hasKnownLabels(%j) is %s', (rows, expected) => {
        expect(hasKnownLabels(rows)).toEqual(expected)
    })

    const d1Row: ReliabilityRow = { bucket: 'd1', calls: 4, errors: 1, p50: 10, p95: 30 }
    test.each<[string, ReliabilityRow[], string[], number[], number[], number[]]>([
        ['a normal bucket', [d1Row], ['d1'], [25], [10], [30]],
        ['a bucket with no calls', [], ['d1'], [NaN], [NaN], [NaN]],
        ['a gap next to a bucket with calls', [d1Row], ['d1', 'd2'], [25, NaN], [10, NaN], [30, NaN]],
    ])('buildReliabilitySeries handles %s', (_name, rows, bucketKeys, errorRatePct, p50, p95) => {
        expect(buildReliabilitySeries(rows, bucketKeys)).toEqual({ labels: bucketKeys, errorRatePct, p50, p95 })
    })

    test.each([
        ['numbers', 12, 40, [12, 40]],
        ['null quantiles', null, null, [NaN, NaN]],
        ['missing quantiles', undefined, undefined, [NaN, NaN]],
        ['a mix of number and null', 12, null, [12, NaN]],
    ])('toReliabilityRows keeps %s as gaps not zeros', (_name, p50, p95, expected) => {
        const [result] = toReliabilityRows([['2026-01-01 00:00:00', 4, 1, p50, p95]])
        expect([result.p50, result.p95]).toEqual(expected)
    })

    test.each([
        ['one lab ahead', [labShare('Anthropic', 60), labShare('OpenAI', 30), labShare('xAI', 10)], ['Anthropic']],
        [
            'a tie at the top',
            [labShare('OpenAI', 40), labShare('Anthropic', 40), labShare('xAI', 20)],
            ['OpenAI', 'Anthropic'],
        ],
        ['every share is zero', [labShare('Anthropic', 0), labShare('OpenAI', 0)], []],
        ['no labs', [], []],
    ])('leadingLabs: %s', (_name, shares, expected) => {
        expect(leadingLabs(shares)).toEqual(expected)
    })
})
