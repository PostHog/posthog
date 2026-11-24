import type { LiveQueryKey } from '@/api/live'
import {
    liveActivity,
    liveBreakdown,
    liveEvents,
    livePathCounts,
    liveRankedRows,
    liveReferrerCounts,
    liveUsersOnlineFromQuery,
    liveWorld,
} from '@/model/adapters/live'

import { DEFAULT_LIVE_TRAFFIC_FILTERS } from '@/model/liveTrafficFilters'

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
    test.each(['app_only', 'mixed'] as const)('%s fixtures include mobile screens and platform data', (state) => {
        const demo = new LiveDemo(1105, START, state)
        const activity = liveActivity(demo.respond('usersPageviews', START), START)
        expect(activity.screenviews).toBeGreaterThan(0)
        expect(livePathCounts(demo.respond('screens', START)).size).toBeGreaterThan(0)
        const platforms = liveBreakdown(demo.respond('platforms', START), 'platforms')
        expect(platforms.rows.map((row) => row.label).sort()).toEqual(['Android', 'iOS'])
        expect(liveEvents(demo.respond('recentEvents', START)).some((event) => event.kind === 'screen')).toBe(true)
        expect(activity.pageviews === 0).toBe(state === 'app_only')
        const same = new LiveDemo(1105, START, state)
        expect(same.respond('mobileMetrics', START)).toEqual(demo.respond('mobileMetrics', START))
    })

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
        expect(liveWorld(demo.respond('geo', now)).countries.length).toBeGreaterThanOrEqual(15)
        expect(liveEvents(demo.respond('recentEvents', now))).toHaveLength(50)
        expect(liveUsersOnlineFromQuery(demo.respond('usersOnline', now))).toBeGreaterThan(0)
    })

    test('bot, host and literal path filters narrow the same fixture across every card', () => {
        const demo = new LiveDemo(1105, START, 'mixed')
        const all = liveActivity(demo.respond('usersPageviews', START), START)
        const people = { ...DEFAULT_LIVE_TRAFFIC_FILTERS, excludeBots: true }
        const humans = liveActivity(demo.respond('usersPageviews', START, people), START)
        expect(humans.pageviews).toBeLessThan(all.pageviews)
        const filters = { ...people, hostname: 'app.hedgebox.net', pathPrefix: '/files', pathMode: 'prefix' as const }
        const events = liveEvents(demo.respond('recentEvents', START, filters))
        expect(events.length).toBeGreaterThan(0)
        expect(events.every(({ url }) => url?.startsWith('https://app.hedgebox.net/files'))).toBe(true)
        const activity = liveActivity(demo.respond('usersPageviews', START, filters), START)
        expect(activity.uniqueVisitors).toBe(liveWorld(demo.respond('geo', START, filters)).total)
        expect(activity.screenviews).toBe(0)
        expect(activity.pageviews).toBeLessThan(humans.pageviews)
        expect(demo.respond('mobileMetrics', START, filters)).toEqual({ results: [[0, 0, 0, 0, 0]] })
        expect(demo.respond('usersOnline', START, { ...filters, hostname: 'no-match.example.com' })).toEqual({
            results: [[0]],
        })
    })

    test('combines acquisition, location and device criteria for every current and historical view', () => {
        const demo = new LiveDemo(1105, START, 'mixed')
        const filters = {
            ...DEFAULT_LIVE_TRAFFIC_FILTERS,
            countryCode: 'US',
            deviceType: 'Mobile',
            referringDomain: 'google.com',
            channelType: 'Organic Search',
        }
        const activity = liveActivity(demo.respond('usersPageviews', START, filters), START)
        expect(activity.pageviews).toBeGreaterThan(0)
        expect(liveWorld(demo.respond('geo', START, filters)).counts).toEqual({ US: activity.uniqueVisitors })
        expect(liveBreakdown(demo.respond('device', START, filters), 'devices').rows.map(({ label }) => label)).toEqual(
            ['Mobile']
        )
        expect([...liveReferrerCounts(demo.respond('referrer', START, filters))]).toEqual([
            ['google.com', activity.pageviews],
        ])
        const events = liveEvents(demo.respond('recentEvents', START, filters))
        expect(events.length).toBeGreaterThan(0)
        expect(events.every(({ sessionId }) => sessionId)).toBe(true)
        const unmatched = { ...filters, channelType: 'Direct' }
        expect(liveEvents(demo.respond('recentEvents', START, unmatched))).toEqual([])
        expect(demo.respond('mobileMetrics', START, unmatched)).toEqual({ results: [[0, 0, 0, 0, 0]] })
        const history = demo.respond('mobileMetrics', START, filters)
        expect(history).toEqual({ results: [[expect.any(Number), expect.any(Number), 9, 46, expect.any(Number)]] })
    })

    test('exact paths and prefixes select different sets of events', () => {
        const demo = new LiveDemo(1105, START, 'mixed')
        const exact = {
            ...DEFAULT_LIVE_TRAFFIC_FILTERS,
            hostname: 'app.hedgebox.net',
            pathPrefix: '/files',
            pathMode: 'exact' as const,
        }
        const exactEvents = liveEvents(demo.respond('recentEvents', START, exact))
        const prefixEvents = liveEvents(demo.respond('recentEvents', START, { ...exact, pathMode: 'prefix' }))
        expect(exactEvents.length).toBeGreaterThan(0)
        expect(exactEvents.every(({ place }) => place === '/files')).toBe(true)
        expect(prefixEvents.some(({ place }) => place === '/files/shared')).toBe(true)
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
