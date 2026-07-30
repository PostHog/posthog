import { makeQuota } from './quotaTestUtils'
import { STARTUP_CAP_CREDITS, applyStartupCap } from './startupCap'

describe('applyStartupCap', () => {
    it.each([
        ['fills in the cap when billing reports no limit', null, STARTUP_CAP_CREDITS],
        ['clamps a limit above the cap', STARTUP_CAP_CREDITS + 100_000, STARTUP_CAP_CREDITS],
        ['keeps a self-set limit below the cap', 5_000, 5_000],
        ['keeps a limit equal to the cap', STARTUP_CAP_CREDITS, STARTUP_CAP_CREDITS],
    ])('%s', (_name, creditLimit: number | null, expected: number) => {
        const capped = applyStartupCap(makeQuota({ credit_limit: creditLimit }), STARTUP_CAP_CREDITS)

        expect(capped?.credit_limit).toBe(expected)
    })

    it.each([
        ['no cap applies', makeQuota({ credit_limit: null }), null],
        ['there is no quota yet', null, STARTUP_CAP_CREDITS],
    ])('passes the quota through untouched when %s', (_name, quota, cap) => {
        expect(applyStartupCap(quota, cap)).toBe(quota)
    })

    it('recomputes remaining against the capped limit', () => {
        const quota = makeQuota({ credit_limit: null, credits_used: 1_000, remaining: null })

        expect(applyStartupCap(quota, STARTUP_CAP_CREDITS)?.remaining).toBe(STARTUP_CAP_CREDITS - 1_000)
    })
})
