import { dayjs } from 'lib/dayjs'

import { joinCitedAndLanded, normalizePagePath, resolveAiTrafficWindow } from './aiTraffic'

describe('aiTraffic', () => {
    test.each([
        ['https://www.example.com/docs/setup/?ref=answer#install', '/docs/setup'],
        ['https://example.com', '/'],
        ['https://example.com/', '/'],
        ['/pricing/', '/pricing'],
        ['/pricing', '/pricing'],
        ['/', '/'],
        ['blog/post?utm_source=assistant', '/blog/post'],
    ])('normalizes %s to %s', (input, expected) => {
        expect(normalizePagePath(input)).toBe(expected)
    })

    it('joins cited pages with landing pages by normalized path and marks one-sided pages', () => {
        const rows = joinCitedAndLanded(
            [
                { path: '/docs/setup', answers: 4 },
                { path: '/docs/setup/', answers: 1 },
                { path: '/pricing', answers: 2 },
                { path: '/blog/old-post', answers: 6 },
            ],
            [
                { path: '/docs/setup/', sessions: 30 },
                { path: '/pricing', sessions: 3 },
                { path: '/', sessions: 50 },
            ]
        )

        expect(rows).toEqual([
            { path: '/docs/setup', answers: 5, sessions: 30, status: 'cited_and_visited' },
            { path: '/pricing', answers: 2, sessions: 3, status: 'cited_and_visited' },
            { path: '/blog/old-post', answers: 6, sessions: 0, status: 'cited_not_visited' },
            { path: '/', answers: 0, sessions: 50, status: 'visited_not_cited' },
        ])
    })

    test.each([
        [
            'a relative start runs to now',
            { dateFrom: '-30d', dateTo: null },
            { start: '2026-10-11 00:00:00', end: '2026-11-10 15:30:00' },
        ],
        [
            'a bare end date covers that whole day',
            { dateFrom: '2026-10-01', dateTo: '2026-10-07' },
            { start: '2026-10-01 00:00:00', end: '2026-10-07 23:59:59' },
        ],
    ])('resolves the citation window: %s', (_, range, expected) => {
        jest.useFakeTimers()
        try {
            jest.setSystemTime(new Date('2026-11-10T15:30:00Z'))
            expect(resolveAiTrafficWindow(range, 'UTC', dayjs().tz('UTC'))).toEqual(expected)
        } finally {
            jest.useRealTimers()
        }
    })
})
