import type { ReplayScannerApi, VisionQuotaApi } from '../generated/api.schemas'
import { type WatchFeedEmptyReason, resolveWatchFeedEmptyReason } from './watchFeedEmptyState'

const scanner = (overrides: Partial<ReplayScannerApi> = {}): ReplayScannerApi =>
    ({ id: 'scanner-1', enabled: true, limit_reached: false, ...overrides }) as unknown as ReplayScannerApi

const quota = (exhausted: boolean): VisionQuotaApi => ({ exhausted }) as unknown as VisionQuotaApi

describe('resolveWatchFeedEmptyReason', () => {
    // The precedence between these is the behavior under test: a reader told to clear their filters
    // while every scanner is off would clear them and still face an empty feed.
    it.each<[string, ReplayScannerApi[], VisionQuotaApi | null, boolean, WatchFeedEmptyReason]>([
        ['no scanners at all', [], quota(false), false, 'no-scanners'],
        [
            'an exhausted budget, even with every scanner off',
            [scanner({ enabled: false })],
            quota(true),
            false,
            'quota-exhausted',
        ],
        [
            'every scanner off',
            [scanner({ enabled: false }), scanner({ id: 'b', enabled: false })],
            quota(false),
            false,
            'all-disabled',
        ],
        // Guards the empty-array trap: `[].every()` answers true, so the disabled check has to come first.
        ['every scanner off rather than capped', [scanner({ enabled: false })], quota(false), false, 'all-disabled'],
        [
            'every running scanner capped',
            [scanner({ limit_reached: true }), scanner({ id: 'b', limit_reached: true })],
            quota(false),
            false,
            'all-capped',
        ],
        [
            'a block rather than the filters holding it back',
            [scanner({ enabled: false })],
            quota(false),
            true,
            'all-disabled',
        ],
        ['the filters, once nothing else blocks the feed', [scanner()], quota(false), true, 'filtered'],
        ['a quiet window while the fleet is healthy', [scanner()], quota(false), false, 'quiet-window'],
        // A capped scanner the reader already turned off says nothing about the ones still running.
        [
            'a quiet window despite a disabled capped scanner',
            [scanner({ enabled: false, limit_reached: true }), scanner({ id: 'b' })],
            quota(false),
            false,
            'quiet-window',
        ],
        // Falls through rather than claiming a block it cannot see.
        ['a quiet window when the quota snapshot never answered', [scanner()], null, false, 'quiet-window'],
    ])('blames %s', (_name, scanners, quotaValue, hasFeedFilters, expected) => {
        expect(resolveWatchFeedEmptyReason({ scanners, quota: quotaValue, hasFeedFilters })).toBe(expected)
    })
})
