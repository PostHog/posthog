import type { TransactionalEmailLogEventApi } from 'products/messaging/frontend/generated/api.schemas'

import { MAX_SHOWN_CLICKS, emailClickRows, hasMoreClicks } from './emailClicks'

const click = (at: string): TransactionalEmailLogEventApi => ({ kind: 'clicked', at, reason: null })

describe('emailClicks', () => {
    it.each([
        [
            'pairs each click with the link recorded at the same instant',
            [click('2026-03-10T09:05:00Z'), click('2026-03-10T09:06:00Z')],
            [
                { at: '2026-03-10T09:06:00.000000+00:00', link: 'https://example.com/docs' },
                { at: '2026-03-10T09:05:00.000Z', link: 'https://example.com/billing' },
            ],
            ['https://example.com/billing', 'https://example.com/docs'],
        ],
        [
            'gives two clicks at one instant a link each',
            [click('2026-03-10T09:05:00Z'), click('2026-03-10T09:05:00Z')],
            [
                { at: '2026-03-10T09:05:00Z', link: 'https://example.com/a' },
                { at: '2026-03-10T09:05:00Z', link: 'https://example.com/b' },
            ],
            ['https://example.com/a', 'https://example.com/b'],
        ],
        [
            'leaves a click without a recorded link empty',
            [{ kind: 'opened', at: '2026-03-10T09:01:00Z', reason: null }, click('2026-03-10T09:05:00Z')],
            [{ at: '2026-03-10T09:05:00Z', link: null }],
            [null],
        ],
    ] as const)('%s', (_name, timeline, links, expected) => {
        expect(emailClickRows(timeline, links).map((row) => row.link)).toEqual(expected)
    })

    it('shows only the newest clicks', () => {
        const timeline = Array.from({ length: MAX_SHOWN_CLICKS + 1 }, (_, index) =>
            click(new Date(Date.UTC(2026, 2, 10, 9, 0, index)).toISOString())
        )
        const rows = emailClickRows(timeline, [])
        expect([rows.length, rows[0].at, hasMoreClicks(timeline)]).toEqual([MAX_SHOWN_CLICKS, timeline[1].at, true])
    })
})
