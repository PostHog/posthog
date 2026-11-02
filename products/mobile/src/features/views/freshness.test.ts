import { recordServerDate, resetServerClock } from '@/api/serverClock'
import type { Freshness } from '@/model/views'

import { blockedState, dueAt, isEligible, refreshHintText, statusLine } from './freshness'

const T = Date.parse('2026-10-14T12:00:00Z')
const MIN = 60_000

function snap(overrides: Partial<Freshness>): Freshness {
    return {
        lastRefreshAt: new Date(T - 10 * MIN).toISOString(),
        cacheTargetAge: new Date(T + 6 * 60 * MIN).toISOString(),
        nextAllowedRefreshAt: new Date(T + 5 * MIN).toISOString(),
        readAt: T - 10 * MIN,
        refreshFailed: false,
        ...overrides,
    }
}

describe('freshness', () => {
    afterEach(() => {
        resetServerClock()
        jest.useRealTimers()
    })

    test.each<[string, Freshness | undefined, number, number]>([
        ['an item never read', undefined, 0, 0],
        ['a good value far from its target age', snap({ readAt: T }), 0, T + 5 * MIN],
        [
            'a target age two minutes after the read',
            snap({ readAt: T, cacheTargetAge: new Date(T + 2 * MIN).toISOString() }),
            0,
            T + 2 * MIN,
        ],
        [
            'a target age that passed, inside the read floor',
            snap({ readAt: T, cacheTargetAge: new Date(T - MIN).toISOString() }),
            0,
            T + MIN,
        ],
        ['no good value', snap({ readAt: T, lastRefreshAt: null }), 0, T + MIN],
        // The server clock is 3 minutes ahead, so its target age arrives 3 minutes earlier on the device.
        [
            'a target age with a server clock ahead',
            snap({ readAt: T, cacheTargetAge: new Date(T + 4 * MIN).toISOString() }),
            3 * MIN,
            T + MIN,
        ],
    ])('dueAt for %s', (_name, snapshot, offsetMs, expected) => {
        expect(dueAt(snapshot, offsetMs)).toBe(expected)
    })

    test.each<[string, string, Partial<Freshness>, boolean]>([
        ['past its window in server time', 'Wed, 14 Oct 2026 12:05:03 GMT', {}, true],
        ['inside the 2 s margin', 'Wed, 14 Oct 2026 12:05:01 GMT', {}, false],
        ['a device clock ahead of the server', 'Wed, 14 Oct 2026 11:50:00 GMT', {}, false],
        ['an item without a good value', 'Wed, 14 Oct 2026 13:00:00 GMT', { lastRefreshAt: null }, false],
        ['an item read under a minute ago', 'Wed, 14 Oct 2026 13:00:00 GMT', { readAt: T + 10 * MIN - 30_000 }, true],
        ['no known refresh window', 'Wed, 14 Oct 2026 13:00:00 GMT', { nextAllowedRefreshAt: null }, false],
        ['an invalid refresh window', 'Wed, 14 Oct 2026 13:00:00 GMT', { nextAllowedRefreshAt: 'invalid' }, false],
    ])('isEligible %s', (_name, serverDate, overrides, expected) => {
        jest.useFakeTimers({ now: T + 10 * MIN })
        recordServerDate(serverDate)

        expect(isEligible(snap(overrides))).toBe(expected)
    })

    test.each<[string, (Freshness | undefined)[], boolean, string | null]>([
        ['a running request', [snap({})], true, 'Updating…'],
        [
            'the oldest of several values',
            [snap({}), snap({ lastRefreshAt: new Date(T - 3 * 60 * MIN).toISOString() })],
            false,
            'Updated 3 h ago',
        ],
        [
            'values from the last minute',
            [snap({ lastRefreshAt: new Date(T - 20_000).toISOString() })],
            false,
            'Updated just now',
        ],
        [
            'a failed read',
            [snap({ refreshFailed: true, lastRefreshAt: new Date(T - 20_000).toISOString() })],
            false,
            "Couldn't refresh. Updated 1 min ago",
        ],
        ['no data items', [undefined, snap({ lastRefreshAt: null })], false, null],
    ])('statusLine for %s', (_name, snapshots, busy, expected) => {
        expect(statusLine(snapshots, busy, T).text).toBe(expected)
    })

    test.each<[string, Freshness[], number | null, { blocked: boolean; until: number | null; reason: string | null }]>([
        [
            'an eligible item',
            [snap({ nextAllowedRefreshAt: new Date(T - MIN).toISOString() })],
            null,
            { blocked: false, until: null, reason: null },
        ],
        [
            'every item inside its window',
            [snap({}), snap({ nextAllowedRefreshAt: new Date(T + 2 * MIN).toISOString() })],
            null,
            { blocked: true, until: T + 2 * MIN + 2000, reason: 'item_window' },
        ],
        [
            'an item without a value',
            [snap({}), snap({ lastRefreshAt: null })],
            null,
            { blocked: false, until: null, reason: null },
        ],
        [
            'an item read under a minute ago',
            [snap({ nextAllowedRefreshAt: new Date(T - MIN).toISOString(), readAt: T - 20_000 })],
            null,
            { blocked: false, until: null, reason: null },
        ],
        [
            'a shared dashboard floor past the item windows',
            [snap({ nextAllowedRefreshAt: new Date(T - MIN).toISOString() })],
            T + 4 * MIN,
            { blocked: true, until: T + 4 * MIN, reason: 'dashboard_floor' },
        ],
        [
            'no known refresh window',
            [snap({ nextAllowedRefreshAt: null })],
            null,
            { blocked: true, until: null, reason: 'item_window' },
        ],
    ])('blockedState for %s', (_name, snapshots, floor, expected) => {
        expect(blockedState({ snapshots, dashboardFloorUntil: floor, now: T })).toEqual(expected)
    })

    test.each([
        [null, 'Showing the latest available data.'],
        [Number.NaN, 'Showing the latest available data.'],
        [T - MIN, 'Showing the latest available data.'],
        [T + MIN, 'You can refresh again in 1 min.'],
    ])('refresh hint for %s never invents a countdown', (until, expected) => {
        expect(refreshHintText(until, T)).toBe(expected)
    })
})
