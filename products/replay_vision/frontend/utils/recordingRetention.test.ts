import { dayjs } from 'lib/dayjs'

import type { SessionRecordingRetentionPeriod } from '~/types'

import { recordingLikelyExpired, recordingRetentionDays } from './recordingRetention'

describe('recordingRetention', () => {
    it.each([
        ['30d', 30],
        ['90d', 90],
        ['1y', 365],
        ['5y', 1825],
        [null, 30],
        ['legacy', null],
    ] as [SessionRecordingRetentionPeriod | null, number | null][])(
        'a %s retention period reads as %s days',
        (period, expectedDays) => {
            expect(recordingRetentionDays(period)).toBe(expectedDays)
        }
    )

    it('flags only observations older than the retention period, and never a legacy-retention project', () => {
        const withinRetention = dayjs().subtract(29, 'day').toISOString()
        const pastRetention = dayjs().subtract(31, 'day').toISOString()
        expect(recordingLikelyExpired(withinRetention, '30d')).toBe(false)
        expect(recordingLikelyExpired(pastRetention, '30d')).toBe(true)
        expect(recordingLikelyExpired(pastRetention, '90d')).toBe(false)
        expect(recordingLikelyExpired(pastRetention, null)).toBe(true)
        expect(recordingLikelyExpired(pastRetention, 'legacy')).toBe(false)
    })
})
