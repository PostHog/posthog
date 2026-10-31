import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../utils/quotaTestUtils'
import { stoppedByFreeCredits } from './scannerCopy'
import { ScannerStatusFields, scannerStatus, spendAgainstLimit } from './scannerStatus'

const NOW = dayjs('2026-05-12T12:00:00Z')

// A healthy, long-running scanner: swept on schedule, its watermark trailing by the settle window.
const HEALTHY: ScannerStatusFields = {
    enabled: true,
    sampling_rate: 1,
    limit_reached: false,
    credit_limit: null,
    limit_from_free_credits: false,
    sweep_throttle_factor: 1,
    created_at: '2026-05-01T00:00:00Z',
    last_swept_at: NOW.subtract(40, 'minute').toISOString(),
    filter_error: null,
}

const DROUGHT = { everScanned: true, samplingRate: 1 }

// A new scanner's watermark starts one settle window before creation and only moves once a sweep finishes.
const createdMinutesAgo = (minutes: number): Partial<ScannerStatusFields> => ({
    created_at: NOW.subtract(minutes, 'minute').toISOString(),
    last_swept_at: NOW.subtract(minutes + 35, 'minute').toISOString(),
})

describe('scannerStatus', () => {
    test.each([
        ['running when nothing is wrong', {}, {}, 'running'],
        ['off wins over every other problem', { enabled: false, limit_reached: true }, { quotaExhausted: true }, 'off'],
        ['off at 0% sampling, ahead of a reached limit', { sampling_rate: 0, limit_reached: true }, {}, 'off'],
        [
            "the scanner's own limit ahead of the org quota",
            { limit_reached: true },
            { quotaExhausted: true },
            'limit_reached',
        ],
        ['stopped when the org quota is used up', {}, { quotaExhausted: true }, 'quota_exhausted'],
        [
            'filter error ahead of the delay it causes',
            { filter_error: 'Unable to resolve field: event', last_swept_at: NOW.subtract(3, 'hour').toISOString() },
            {},
            'filter_error',
        ],
        ['starting while the first sweep has not finished', createdMinutesAgo(10), {}, 'starting'],
        ['delayed once a first sweep is over an hour late', createdMinutesAgo(70), {}, 'delayed'],
        [
            'delayed when sweeps stopped advancing',
            { last_swept_at: NOW.subtract(3, 'hour').toISOString() },
            {},
            'delayed',
        ],
        [
            'not delayed while a throttled sweep waits out its longer interval',
            { sweep_throttle_factor: 12, last_swept_at: NOW.subtract(2, 'hour').toISOString() },
            {},
            'throttled',
        ],
        [
            'delayed ahead of no matches, since no sweep ran to match anything',
            { last_swept_at: NOW.subtract(3, 'hour').toISOString() },
            { drought: DROUGHT },
            'delayed',
        ],
        ['no matches ahead of throttled', { sweep_throttle_factor: 3 }, { drought: DROUGHT }, 'no_matches'],
        ['throttled when the read budget stretches the cadence', { sweep_throttle_factor: 3 }, {}, 'throttled'],
    ])('%s', (_name, scannerOverrides, options, expected) => {
        const status = scannerStatus(
            { ...HEALTHY, ...scannerOverrides },
            { quotaExhausted: false, drought: null, now: NOW, ...options }
        )
        expect(status.kind).toBe(expected)
    })

    it('reports the stretched interval so the strip can say how often it checks', () => {
        expect(
            scannerStatus({ ...HEALTHY, sweep_throttle_factor: 12 }, { quotaExhausted: false, drought: null, now: NOW })
        ).toMatchObject({
            kind: 'throttled',
            intervalMinutes: 60,
        })
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
        ['an own limit blames that limit', { credit_limit: 500 }, false],
        ['no own limit blames the free credits', { credit_limit: null }, true],
        [
            'an own limit blames the free credits when they bind',
            { credit_limit: 500, limit_from_free_credits: true },
            true,
        ],
    ])('stopped free-only scanner with %s', (_name, overrides, expected) => {
        const status = scannerStatus(
            { ...HEALTHY, free_only: true, limit_reached: true, ...overrides },
            { quotaExhausted: false, drought: null, now: NOW }
        )
        expect(status.kind === 'limit_reached' && stoppedByFreeCredits(status)).toBe(expected)
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
})
