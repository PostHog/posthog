import { describe, expect, it } from 'vitest'

import { decide429Retry, MAX_RETRIES, MAX_RETRY_AFTER_MS } from '@/api/retry'

describe('decide429Retry', () => {
    it.each([
        { header: '5', attempt: 0, delayMs: 5000 },
        { header: '0', attempt: 0, delayMs: 0 },
        { header: String(MAX_RETRY_AFTER_MS / 1000), attempt: 0, delayMs: MAX_RETRY_AFTER_MS },
    ])('retries with the Retry-After delay when within the cap (header: $header)', ({ header, attempt, delayMs }) => {
        expect(decide429Retry(header, attempt)).toEqual({ retry: true, delayMs })
    })

    it('fails fast when Retry-After exceeds the cap', () => {
        expect(decide429Retry('3600', 0)).toEqual({
            retry: false,
            delayMs: 3_600_000,
            reason: 'retry_after_exceeds_cap',
        })
    })

    it('stops retrying once attempts are exhausted', () => {
        expect(decide429Retry('5', MAX_RETRIES)).toEqual({ retry: false, delayMs: 0, reason: 'exhausted' })
    })

    it.each([
        { header: null, attempt: 0, min: 1000, max: 2000 },
        { header: null, attempt: 1, min: 2000, max: 4000 },
        { header: null, attempt: 2, min: 4000, max: 8000 },
        { header: 'Wed, 21 Oct 2026 07:28:00 GMT', attempt: 0, min: 1000, max: 2000 },
        { header: '-5', attempt: 0, min: 1000, max: 2000 },
    ])(
        'falls back to jittered exponential backoff for missing or invalid Retry-After (header: $header, attempt: $attempt)',
        ({ header, attempt, min, max }) => {
            const decision = decide429Retry(header, attempt)
            expect(decision.retry).toBe(true)
            expect(decision.delayMs).toBeGreaterThanOrEqual(min)
            expect(decision.delayMs).toBeLessThanOrEqual(max)
        }
    )
})
