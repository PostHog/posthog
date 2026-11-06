import type { LiveRankedRow } from '@/model/live'

import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
    liveUsersOnlineFromStats,
} from './live'

const NOW = Date.parse('2026-11-05T21:14:30Z')

function minute(time: string): string {
    return `2026-11-05T${time}:00Z`
}

function ranked(keys: string[]): LiveRankedRow[] {
    return keys.map((key) => ({ key, label: key, views: 1, percent: 0, rankDelta: null, direct: false }))
}

describe('live adapters', () => {
    test('minute buckets split new and returning visitors and count only the 30 minutes on screen', () => {
        const activity = liveActivity(
            {
                results: [
                    [minute('20:44'), ['early'], 9],
                    [minute('20:45'), ['a', 'b'], 3],
                    [minute('20:50'), ['a', 'c'], 2],
                    ['2026-11-05T16:14:00-05:00', ['c'], 1],
                ],
            },
            NOW
        )
        expect(activity.minutes).toHaveLength(30)
        expect(activity.minutes[0]).toEqual({
            at: Date.parse(minute('20:45')),
            users: 2,
            newUsers: 2,
            returningUsers: 0,
            pageviews: 3,
        })
        expect(activity.minutes[5]).toMatchObject({ users: 2, newUsers: 1, returningUsers: 1 })
        expect(activity.minutes[29]).toMatchObject({ users: 1, newUsers: 0, returningUsers: 1, pageviews: 1 })
        expect(activity.minutes[1]).toMatchObject({ users: 0, pageviews: 0 })
        expect(activity).toMatchObject({ uniqueVisitors: 3, pageviews: 6 })
    })

    test('ranked rows carry their share and how far they moved, and equal counts keep their order', () => {
        const rows = liveRankedRows(
            new Map([
                ['/', 10],
                ['/pricing', 8],
                ['/signup', 5],
                ['/login', 4],
                ['/new', 3],
                ['/b', 2],
                ['/a', 2],
            ]),
            40,
            ranked(['/', '/pricing', '/login', '/signup', '/b', '/a'])
        )
        expect(rows.map((row) => [row.key, row.rankDelta])).toEqual([
            ['/', null],
            ['/pricing', null],
            ['/signup', 1],
            ['/login', -1],
            ['/new', null],
            ['/b', -1],
            ['/a', -1],
        ])
        expect(rows[2]?.percent).toBe(12.5)
        expect(liveRankedRows(new Map([['/', 1]]), 0, null)[0]).toMatchObject({ percent: 0, rankDelta: null })
    })

    test('referrers sum over minutes, an empty domain is direct, and paths skip the no-path placeholder', () => {
        const referrers = liveReferrerCounts({
            results: [
                [minute('21:00'), 'google.com', 4],
                [minute('21:01'), 'google.com', 2],
                [minute('21:01'), '', 3],
                [minute('21:02'), '$direct', 1],
            ],
        })
        expect(liveRankedRows(referrers, 10, null)).toEqual([
            { key: 'google.com', label: 'google.com', views: 6, percent: 60, rankDelta: null, direct: false },
            { key: '$direct', label: 'Direct / None', views: 4, percent: 40, rankDelta: null, direct: true },
        ])
        expect(
            livePathCounts({
                results: [
                    { breakdown_value: '/pricing', data: [1, 0, 2] },
                    { breakdown_value: '$$_posthog_breakdown_null_$$', data: [5] },
                ],
            })
        ).toEqual(new Map([['/pricing', 3]]))
    })

    test.each([
        ['devices', 'unique devices', ['Mobile', 'Desktop', 'Tablet', 'TV', 'Watch', 'Car', 'Fridge'], 7],
        ['browsers', 'unique browsers', ['Chrome', 'Safari', 'Firefox', 'Edge', 'Brave', 'Opera', 'Arc', 'Vivaldi'], 7],
    ] as const)(
        '%s count distinct ids per value, and only browsers fold the tail into Other',
        (kind, statLabel, values, rows) => {
            const idsByValue = Object.fromEntries(
                values.map((value, index) => [
                    value,
                    Array.from({ length: values.length - index }, (_, id) => `${value}-${id}`),
                ])
            )
            const breakdown = liveBreakdown(
                {
                    results: [
                        [minute('21:00'), idsByValue],
                        [minute('21:10'), { [values[0]]: [`${values[0]}-0`, 'returning-later'] }],
                        [minute('20:00'), { [values[0]]: ['outside-the-window'] }],
                    ],
                },
                kind,
                NOW
            )
            expect(breakdown.statLabel).toBe(statLabel)
            expect(breakdown.rows).toHaveLength(rows)
            expect(breakdown.rows[0]).toMatchObject({ key: values[0], count: values.length + 1 })
            expect(breakdown.total).toBe(breakdown.rows.reduce((sum, row) => sum + row.count, 0))
            if (kind === 'browsers') {
                expect(breakdown.rows.at(-1)).toMatchObject({ key: 'Other', count: 3 })
            }
        }
    )

    test('country rows show a flag and a name, and an unknown code stays a code', () => {
        const breakdown = liveBreakdown(
            { results: [[minute('21:05'), { US: ['a', 'b', 'c'], GB: ['d'], XK: ['e'] }]] },
            'countries',
            NOW
        )
        expect(breakdown.rows.map((row) => [row.label, row.flag, row.percent])).toEqual([
            ['United States', '🇺🇸', 60],
            ['United Kingdom', '🇬🇧', 20],
            ['XK', '🇽🇰', 20],
        ])
    })

    test('events come newest first with a readable name and the most specific place', () => {
        const events = liveEvents({
            results: [
                ['e1', '$pageview', 'person-1', 1000, 'https://hedgebox.net/pricing', null, '/pricing', 'session-1'],
                ['e2', '$screen', 'person-2', 3000, null, 'Upload', null, null],
                ['e3', 'file_uploaded', 'person-1', '2000', 'https://app.hedgebox.net/files', null, null, null],
                [null, '$pageview', 'person-3', 4000, null, null, '/', null],
            ],
        })
        expect(events.map((event) => [event.id, event.label, event.kind, event.place, event.at])).toEqual([
            ['e2', 'Screen', 'screen', 'Upload', 3000],
            ['e3', 'file_uploaded', 'other', 'https://app.hedgebox.net/files', 2000],
            ['e1', 'Pageview', 'pageview', '/pricing', 1000],
        ])
        expect(events[2]).toMatchObject({ url: 'https://hedgebox.net/pricing', sessionId: 'session-1' })
    })

    test.each([
        ['stats count', () => liveUsersOnlineFromStats({ users_on_product: 12 }), 12],
        ['stats without a count', () => liveUsersOnlineFromStats({}), null],
        ['query count', () => liveUsersOnlineFromQuery({ results: [[7]] }), 7],
        ['query without rows', () => liveUsersOnlineFromQuery({ results: [] }), null],
    ])('users online: %s', (_, read, expected) => {
        expect(read()).toBe(expected)
    })
})
