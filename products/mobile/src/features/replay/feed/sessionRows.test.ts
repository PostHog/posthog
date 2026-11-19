import type { FeedItem, FeedSource } from './feedModel'
import { parseSignals, type SessionSignals, sessionRow } from './sessionRows'

const START = '2026-11-01T10:00:00.000Z'
const NOW = new Date('2026-11-01T12:00:00.000Z')

function item(summary: { title: string; notabilityReason: string | null } | null = null): FeedItem {
    return {
        recording: {
            sessionId: 's1',
            personLabel: 'ari@example.com',
            countryCode: null,
            startedAt: START,
            endedAt: null,
            durationSeconds: 1800,
            clickCount: 20,
            consoleErrorCount: 0,
            startPath: '/checkout',
            ongoing: false,
            activityScore: null,
        },
        summary: summary ? ({ ...summary } as FeedItem['summary']) : null,
        exports: [],
        readyAtLoad: false,
    }
}

const SIGNALS: SessionSignals = {
    rage: [
        { seconds: 30, target: 'Pay now' },
        { seconds: 300, target: 'Add to cart' },
        { seconds: 320, target: 'Add to cart' },
    ],
    errors: [{ seconds: 600, type: 'TypeError', value: 'x is undefined' }],
}

describe('Sessions rows', () => {
    test.each([
        ['rage', null, 'rage', 'Rage click on “Add to cart” ×2'],
        ['errors', null, 'error', 'TypeError: x is undefined'],
        [
            'highlights',
            { title: 'Checkout failed', notabilityReason: 'Card declined twice' },
            'highlight',
            'Card declined twice',
        ],
        ['newest', null, 'error', 'TypeError: x is undefined'],
    ] as const)('on %s the reason line is the strongest signal', (source, summary, reason, text) => {
        const row = sessionRow(item(summary), SIGNALS, source as FeedSource, NOW)
        expect([row.reason, row.reasonText]).toEqual([reason, text])
    })

    test('a recording with no signals and no summary shows its start page and no reason', () => {
        const row = sessionRow(item(), undefined, 'newest', NOW)
        expect(row).toMatchObject({ reason: 'none', reasonText: null, title: '/checkout', marks: [] })
        expect([row.person, row.details]).toEqual(['ari@example.com', '30m 00s · 2h ago'])
    })

    test('hundreds of signals draw a bounded strip, placed by time', () => {
        const rage = Array.from({ length: 500 }, (_unused, index) => ({ seconds: index * 3.6, target: null }))
        const row = sessionRow(item(), { rage, errors: [] }, 'rage', NOW)
        expect(row.marks.length).toBeLessThanOrEqual(40)
        expect(row.marks[0]?.at).toBe(0)
    })

    test('signal rows group by recording, as seconds from its start', () => {
        const signals = parseSignals(
            [
                ['s1', '2026-11-01T10:00:30.000Z', '$rageclick', '["Pay now"]', null, null],
                ['s1', '2026-11-01T10:10:00.000Z', '$exception', null, ['TypeError'], ['x is undefined']],
                ['other', '2026-11-01T10:00:00.000Z', '$rageclick', null, null, null],
            ],
            new Map([['s1', Date.parse(START)]])
        )
        expect(signals.get('s1')).toEqual({
            rage: [{ seconds: 30, target: 'Pay now' }],
            errors: [{ seconds: 600, type: 'TypeError', value: 'x is undefined' }],
        })
        expect(signals.has('other')).toBe(false)
    })
})
