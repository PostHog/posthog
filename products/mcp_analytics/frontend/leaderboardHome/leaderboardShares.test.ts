import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import {
    type BucketedFacetRow,
    buildLabShares,
    buildLabUserShares,
    buildReliabilitySeries,
    harnessErrorRateRows,
    labSqlExpression,
    buildShareSeries,
    hasKnownLabels,
    modelLab,
    toReliabilityRows,
    topFacetRows,
    type ReliabilityRow,
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
            { lab: 'Anthropic', share: 40 },
            { lab: 'OpenAI', share: 10 },
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
            { lab: 'Anthropic', share: 90 },
            { lab: 'OpenAI', share: 60 },
        ])
    })

    it('builds the SQL from the same patterns that modelLab matches', () => {
        const sql = labSqlExpression('m')
        expect(sql).toContain("match(lower(m), 'claude|opus|sonnet|haiku|fable|anthropic'), 'Anthropic'")
        expect(sql.startsWith("multiIf(m = 'Unknown', 'Unknown', ")).toBe(true)
        expect(sql.endsWith(", 'Other')")).toBe(true)
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
})
