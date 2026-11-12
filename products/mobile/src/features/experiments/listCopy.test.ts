import type { ExperimentRow } from './experimentModel'
import { daysToTarget, rowBadge, rowLine, rowLineText, rowMeta } from './listCopy'

const NOW = Date.parse('2026-11-04T07:00:00Z')
const DAY = 24 * 60 * 60_000

function row(overrides: Partial<ExperimentRow>): ExperimentRow {
    return {
        id: '1',
        name: 'Invite reminder',
        flagKey: 'invite-reminder',
        status: 'running',
        method: 'bayes',
        variants: ['control', 'reminder'],
        startedAt: new Date(NOW - 4 * DAY).toISOString(),
        endedAt: null,
        createdAt: new Date(NOW - 5 * DAY).toISOString(),
        days: 4,
        conclusion: null,
        shippedVariant: null,
        changed: false,
        headline: { kind: 'needs_data', exposures: 1200, resultsAt: new Date(NOW - 5 * 60 * 60_000).toISOString() },
        createdBy: { uuid: 'user-1', name: 'Sam Okafor', email: 'sam@example.com' },
        isNew: false,
        targetSampleSize: 2100,
        ...overrides,
    }
}

function text(line: ReturnType<typeof rowLine>): string {
    return line === 'loading' ? 'loading' : rowLineText(line)
}

test('daysToTarget projects the pace so far onto the saved sample target', () => {
    expect(daysToTarget(row({}), NOW)).toBe(3)
    expect(daysToTarget(row({ targetSampleSize: 1000 }), NOW)).toBeNull()
})

test.each<[string, Partial<ExperimentRow>, string, string | null]>([
    [
        'a significant Frequentist loser',
        { headline: { kind: 'significant', leader: 'comparison', delta: -0.14, better: false, pValue: 0.009 } },
        'Significant · comparison −14.0% · p = 0.009',
        'losing',
    ],
    [
        'a significant absolute change, which the row cannot label',
        {
            headline: {
                kind: 'significant',
                leader: 'comparison',
                delta: -1.4,
                differenceType: 'absolute',
                better: false,
                pValue: 0.009,
            },
        },
        'Significant · comparison · p = 0.009',
        'losing',
    ],
    ['a row still reading', { headline: 'loading' }, 'loading', null],
    ['too early to tell', {}, 'Needs more data · ~3 days to target', null],
    ['a fresh launch', { isNew: true, headline: { kind: 'not_yet' } }, 'No results yet · exposures arriving', 'new'],
    [
        'a shipped winner',
        { status: 'complete', conclusion: 'won', shippedVariant: 'compact', headline: 'none' },
        'Won · shipped compact',
        null,
    ],
    [
        'an end without a rollout',
        { status: 'complete', conclusion: 'inconclusive' },
        'Inconclusive · nothing shipped',
        null,
    ],
])('rowLine reads %s', (_name, overrides, expected, badge) => {
    const item = row(overrides)
    expect(text(rowLine(item, NOW))).toBe(expected)
    expect(rowBadge(item)).toBe(badge)
})

test('rowMeta names the person who made a draft and the age of a running result', () => {
    expect(rowMeta(row({ status: 'draft', headline: 'none' }), NOW, 'user-1')).toMatch(
        /^Created \w+ \d+ by you · flag invite-reminder$/
    )
    expect(rowMeta(row({}), NOW, null)).toBe('Running 4 d · 2 variants · 1.2k exposed · 5 h old')
})
