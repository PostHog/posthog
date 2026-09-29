import { dayjs } from 'lib/dayjs'

import { ScannerStatusFields, scannerStatus, spendAgainstLimit } from './scannerStatus'

const NOW = dayjs('2026-05-12T12:00:00Z')

// A healthy, long-running scanner: swept on schedule, its watermark trailing by the settle window.
const HEALTHY: ScannerStatusFields = {
    enabled: true,
    sampling_rate: 1,
    limit_reached: false,
    sweep_throttle_factor: 1,
    created_at: '2026-05-01T00:00:00Z',
    last_swept_at: NOW.subtract(40, 'minute').toISOString(),
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
})
