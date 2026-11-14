import { EMPTY_LIVE_SNAPSHOT } from '@/model/live'
import { liveMobileMetrics, readLiveSnapshot, readLiveWorld } from './liveRead'

describe('Live reads', () => {
    it('keeps missing lifecycle and session tracking unknown for a mobile project', async () => {
        const result = await readLiveSnapshot({
            profile: { kind: 'mobile' },
            previous: EMPTY_LIVE_SNAPSHOT,
            now: 1800000000000,
            signal: new AbortController().signal,
            pathCleaning: false,
            countUsersOnline: false,
            run: async (key) => {
                if (key === 'mobileMetrics') throw new Error('Slow metrics must not block the live read')
                return { results: key === 'mobileSessions' ? [[0, 0]] : key === 'screens' ? [['Home', 12]] : [] }
            },
        })
        expect(result.complete).toBe(true)
        expect(result.data.profile).toEqual({ kind: 'mobile' })
        expect(result.data.topPagesMode).toBe('screens')
        expect(result.data.topPages?.[0]).toMatchObject({ label: 'Home', views: 12 })
        expect(result.data.mobileMetrics).toMatchObject({
            dailyActiveUsers: null,
            weeklyActiveUsers: null,
            installs: null,
            weeklyInstalls: null,
            sessions: null,
        })
        expect(result.data.browsers).toBeNull()
        expect(result.data.topReferrers).toBeNull()
    })

    it('keeps mobile and web top lists separate in mixed mode', async () => {
        const result = await readLiveSnapshot({
            profile: { kind: 'mixed' },
            previous: EMPTY_LIVE_SNAPSHOT,
            now: 1800000000000,
            signal: new AbortController().signal,
            pathCleaning: false,
            countUsersOnline: false,
            run: async (key) => ({
                results:
                    key === 'paths'
                        ? [{ breakdown_value: '/home', data: [4] }]
                        : key === 'screens'
                          ? [{ breakdown_value: 'Home', data: [8] }]
                          : [],
            }),
        })
        expect(result.data.topPagesMode).toBe('pages')
        expect(result.data.topPages?.[0]).toMatchObject({ label: '/home', views: 4 })
        expect(result.data.topScreens?.[0]).toMatchObject({ label: 'Home', views: 8 })
    })

    it('clears stale active-user counts on a successful empty period and retains the original cache timestamp', () => {
        const now = 1800000000000
        expect(liveMobileMetrics({ results: [[0, 0, 0, 0, 0]], liveFetchedAt: now - 1800000 }, now)).toEqual({
            dailyActiveUsers: 0,
            weeklyActiveUsers: 0,
            installs: null,
            weeklyInstalls: null,
            sessions: null,
            updatedAt: now - 1800000,
        })
        expect(liveMobileMetrics({ results: [[5, 20, 0, 0, 40]] }, now)).toMatchObject({
            dailyActiveUsers: 5,
            weeklyActiveUsers: 20,
            installs: null,
        })
        expect(() => liveMobileMetrics({ results: [] }, now)).toThrow('did not finish')
    })

    it('scopes Web activity and its country drilldown while Both keeps project activity', async () => {
        const queries: Record<string, Record<string, unknown>> = {}
        const input = {
            previous: EMPTY_LIVE_SNAPSHOT,
            now: 1800000000000,
            signal: new AbortController().signal,
            pathCleaning: true,
            countUsersOnline: false,
            run: async (key: string, query: Record<string, unknown>) => {
                queries[key] = query
                return { results: [] }
            },
        }
        await readLiveSnapshot({ ...input, profile: { kind: 'web' } })
        expect(queries.usersPageviews?.query).toContain("properties.$lib IN ('web', 'js', 'posthog-js')")
        expect(queries.geo?.query).toContain("properties.$lib IN ('web', 'js', 'posthog-js')")
        expect(queries.paths?.properties).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'OR',
                    values: [
                        { key: '$lib', type: 'event', operator: 'exact', value: ['web', 'js', 'posthog-js', ''] },
                        { key: '$lib', type: 'event', operator: 'is_not_set' },
                    ],
                },
            ],
        })
        await readLiveWorld({ ...input, webOnly: true })
        expect(queries.geo?.query).toContain("properties.$lib IN ('web', 'js', 'posthog-js')")
        await readLiveSnapshot({ ...input, profile: { kind: 'mixed' } })
        expect(queries.usersPageviews?.query).not.toContain('properties.$lib')
        expect(queries.geo?.query).not.toContain('properties.$lib')
        await readLiveSnapshot({ ...input, profile: { kind: 'mobile' } })
        expect(queries.mobileMetrics).toBeUndefined()
        for (const key of ['usersPageviews', 'geo', 'recentEvents', 'mobileSessions', 'screens']) {
            expect(queries[key]?.query).toContain(
                "event = '$screen' AND (properties.$lib IS NULL OR properties.$lib = '') AND lower(properties.$os)"
            )
        }
    })
})
