import { describe, expect, it } from 'vitest'

import { createAdaptivePollSchedule, DEFAULT_ADAPTIVE_POLL_CONFIG } from '@/hono/session-bus/adaptive-poll'

describe('createAdaptivePollSchedule', () => {
    it('returns the hot interval during the hot window', () => {
        const schedule = createAdaptivePollSchedule({
            hotIntervalMs: 200,
            coolIntervalMs: 1_000,
            hotWindowMs: 5_000,
        })
        expect(schedule.nextDelay(0)).toBe(200)
        expect(schedule.nextDelay(2_500)).toBe(200)
        expect(schedule.nextDelay(4_999)).toBe(200)
    })

    it('returns the cool interval after the hot window', () => {
        const schedule = createAdaptivePollSchedule({
            hotIntervalMs: 200,
            coolIntervalMs: 1_000,
            hotWindowMs: 5_000,
        })
        expect(schedule.nextDelay(5_000)).toBe(1_000)
        expect(schedule.nextDelay(60_000)).toBe(1_000)
    })

    it('treats negative elapsed times as hot (defensive)', () => {
        const schedule = createAdaptivePollSchedule({
            hotIntervalMs: 200,
            coolIntervalMs: 1_000,
            hotWindowMs: 5_000,
        })
        expect(schedule.nextDelay(-1)).toBe(200)
    })

    it('uses the documented defaults when no config is provided', () => {
        const schedule = createAdaptivePollSchedule()
        expect(schedule.nextDelay(0)).toBe(DEFAULT_ADAPTIVE_POLL_CONFIG.hotIntervalMs)
        expect(schedule.nextDelay(DEFAULT_ADAPTIVE_POLL_CONFIG.hotWindowMs)).toBe(
            DEFAULT_ADAPTIVE_POLL_CONFIG.coolIntervalMs
        )
    })

    it('rejects non-positive intervals', () => {
        expect(() =>
            createAdaptivePollSchedule({ hotIntervalMs: 0, coolIntervalMs: 1_000, hotWindowMs: 5_000 })
        ).toThrow(/positive/)
        expect(() =>
            createAdaptivePollSchedule({ hotIntervalMs: 200, coolIntervalMs: -1, hotWindowMs: 5_000 })
        ).toThrow(/positive/)
    })

    it('rejects hot interval greater than cool interval', () => {
        expect(() =>
            createAdaptivePollSchedule({ hotIntervalMs: 2_000, coolIntervalMs: 1_000, hotWindowMs: 5_000 })
        ).toThrow(/Hot interval/)
    })
})
