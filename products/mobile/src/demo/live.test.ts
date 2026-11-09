import type { LiveQueryKey } from '@/api/live'
import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
} from '@/model/adapters/live'

import { LiveDemo } from './live'

const START = Date.parse('2026-11-05T21:14:30Z')
const KEYS: LiveQueryKey[] = [
    'usersPageviews',
    'device',
    'browser',
    'paths',
    'referrer',
    'geo',
    'recentEvents',
    'usersOnline',
]

describe('LiveDemo', () => {
    test('answers every live job in the shape the adapters read, with totals that agree', () => {
        const demo = new LiveDemo(1105, START)
        const now = START + 45_000
        const activity = liveActivity(demo.respond('usersPageviews', now), now)
        const pages = liveRankedRows(livePathCounts(demo.respond('paths', now)), activity.pageviews, null)
        const referrers = liveRankedRows(liveReferrerCounts(demo.respond('referrer', now)), activity.pageviews, null)

        expect(activity.uniqueVisitors).toBeGreaterThan(20)
        expect(activity.minutes.every((minute) => minute.users > 0)).toBe(true)
        expect(pages).toHaveLength(10)
        expect(pages.reduce((sum, row) => sum + row.views, 0)).toBeLessThanOrEqual(activity.pageviews)
        expect(referrers.reduce((sum, row) => sum + row.views, 0)).toBe(activity.pageviews)
        expect(liveBreakdown(demo.respond('device', now), 'devices').rows.length).toBeGreaterThan(1)
        expect(liveBreakdown(demo.respond('geo', now), 'countries').total).toBe(activity.uniqueVisitors)
        expect(liveEvents(demo.respond('recentEvents', now))).toHaveLength(50)
        expect(liveUsersOnlineFromQuery(demo.respond('usersOnline', now))).toBeGreaterThan(0)
    })

    test('the same seed gives the same traffic, and time without reads catches up at the next read', () => {
        const a = new LiveDemo(7, START)
        const b = new LiveDemo(7, START)
        const later = START + 5 * 60_000
        for (const key of KEYS) {
            expect(a.respond(key, later)).toEqual(b.respond(key, later))
        }
        const newest = liveEvents(a.respond('recentEvents', later))[0]?.at ?? 0
        expect(later - newest).toBeLessThan(5000)
    })
})
