import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../utils/quotaTestUtils'
import { ScannerStatusFields, isOffByChoice, scannerStatus, spendAgainstLimit } from './scannerStatus'

const NOW = dayjs('2026-05-12T12:00:00Z')

const RUNNING: ScannerStatusFields = {
    status: 'running',
    status_reason: null,
    sweep_interval_minutes: 5,
    last_swept_at: NOW.subtract(40, 'minute').toISOString(),
    filter_error: null,
}

const DROUGHT = { everScanned: true, samplingRate: 1 }

describe('scannerStatus', () => {
    test.each([
        ['running', {}, {}, 'running'],
        [
            'off wins over every project-wide cause',
            { status: 'off' as const },
            { quotaExhausted: true, recordingsBlock: 'replay-off' as const },
            'off',
        ],
        [
            'no sampling ahead of replay being off',
            { status: 'no_sampling' as const },
            { recordingsBlock: 'replay-off' as const },
            'no_sampling',
        ],
        [
            'replay off ahead of the limit it makes moot',
            { status: 'limit_reached' as const },
            { recordingsBlock: 'replay-off' as const },
            'replay_off',
        ],
        [
            'no recordings instead of blaming the filters',
            {},
            { drought: DROUGHT, recordingsBlock: 'no-recordings' as const },
            'no_recordings',
        ],
        [
            "the scanner's own limit ahead of the org quota",
            { status: 'limit_reached' as const },
            { quotaExhausted: true },
            'limit_reached',
        ],
        [
            'the org quota ahead of a filter error',
            { status: 'filter_error' as const },
            { quotaExhausted: true },
            'quota_exhausted',
        ],
        [
            'delayed ahead of no matches, since no sweep ran to match anything',
            { status: 'delayed' as const },
            { drought: DROUGHT },
            'delayed',
        ],
        ['no matches ahead of throttled', { status: 'throttled' as const }, { drought: DROUGHT }, 'no_matches'],
    ])('%s', (_name, scannerOverrides, options, expected) => {
        const status = scannerStatus(
            { ...RUNNING, ...scannerOverrides },
            { quotaExhausted: false, drought: null, now: NOW, ...options }
        )
        expect(status.kind).toBe(expected)
    })

    it.each([
        [
            { status: 'off' as const, status_reason: 'creator_lost_access' as const },
            { kind: 'off', reason: 'creator_lost_access' },
        ],
        [
            { status: 'limit_reached' as const, status_reason: 'free_credits_used' as const },
            { kind: 'limit_reached', freeCredits: true },
        ],
        [
            { status: 'paused' as const, status_reason: 'experiment_not_running' as const },
            { kind: 'paused', reason: 'experiment_not_running' },
        ],
        [{ sweep_interval_minutes: 60 }, { kind: 'running', intervalMinutes: 60 }],
    ])('carries what the copy needs from %o', (overrides, expected) => {
        expect(
            scannerStatus({ ...RUNNING, ...overrides }, { quotaExhausted: false, drought: null, now: NOW })
        ).toMatchObject(expected)
    })

    test.each([
        [null, 0, null],
        [1000, 200, { limit: 1000, used: 200, usedPct: 20 }],
        [1000, 1200, { limit: 1000, used: 1200, usedPct: 100 }],
        [0, 0, { limit: 0, used: 0, usedPct: 0 }],
    ])('spend against a limit of %s with %s used', (credit_limit, credits_used_against_limit, expected) => {
        expect(spendAgainstLimit({ credit_limit, credits_used_against_limit })).toEqual(expected)
    })

    test.each([
        ['org free credits', { credit_limit: 10_000 }, { limit: 2_500, used: 600, usedPct: 24, freeCredits: true }],
        [
            'org limit below the free credits',
            { credit_limit: 1_000 },
            { limit: 1_000, used: 600, usedPct: 60, freeCredits: true },
        ],
        ['uncapped org', { credit_limit: null }, { limit: 2_500, used: 600, usedPct: 24, freeCredits: true }],
    ])('free-only spend against the %s', (_name, quotaOverrides, expected) => {
        const quota = makeQuota({ credits_used: 600, ...quotaOverrides })
        expect(
            spendAgainstLimit({ credit_limit: null, credits_used_against_limit: 0, free_only: true }, quota)
        ).toEqual(expected)
    })

    test.each([
        ['free credits bind', true, 2_400, { limit: 2_500, used: 2_400, usedPct: 96, freeCredits: true }],
        ['own limit binds', false, 300, { limit: 500, used: 300, usedPct: 60 }],
    ])('free-only scanner with its own limit when the %s', (_name, fromFree, usedAgainstLimit, expected) => {
        const quota = makeQuota({ credit_limit: 10_000, credits_used: 2_400 })
        expect(
            spendAgainstLimit(
                {
                    credit_limit: 500,
                    credits_used_against_limit: usedAgainstLimit,
                    free_only: true,
                    limit_from_free_credits: fromFree,
                },
                quota
            )
        ).toEqual(expected)
    })

    test.each([
        ['never turned on', { status: 'off', status_reason: null }, true],
        ['turned off by hand', { status: 'off', status_reason: 'manual' }, true],
        ['already scheduled', { status: 'running', status_reason: null }, false],
        ['out of free credits', { status: 'off', status_reason: 'free_credits_used' }, false],
        ['no AI consent', { status: 'off', status_reason: 'no_ai_consent' }, false],
        ['not loaded', null, false],
    ] as const)('isOffByChoice: %s', (_, scanner, expected) => {
        expect(isOffByChoice(scanner)).toBe(expected)
    })
})
