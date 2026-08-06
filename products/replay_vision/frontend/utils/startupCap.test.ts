import { BillingType, StartupProgramLabel } from '~/types'

import { makeQuota } from './quotaTestUtils'
import { STARTUP_CAP_CREDITS, applyStartupCap, startupCapCredits } from './startupCap'

describe('startupCap', () => {
    it.each([
        ['billing has not loaded', null, null],
        ['the org is not on the startup program', {} as BillingType, null],
        ['the org is enrolled', { startup_program_label: StartupProgramLabel.YC } as BillingType, STARTUP_CAP_CREDITS],
    ])('startupCapCredits when %s', (_name, billing: BillingType | null, expected: number | null) => {
        expect(startupCapCredits(billing)).toBe(expected)
    })

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
        { name: 'no cap applies', quota: makeQuota(), cap: null },
        { name: 'there is no quota yet', quota: null, cap: STARTUP_CAP_CREDITS },
    ])('passes the quota through untouched when $name', ({ quota, cap }) => {
        expect(applyStartupCap(quota, cap)).toBe(quota)
    })

    it.each([
        {
            name: 'recomputes remaining against the cap when spend is under it',
            creditLimit: null,
            creditsUsed: 1_000,
            remaining: STARTUP_CAP_CREDITS - 1_000,
            exhausted: false,
        },
        {
            name: 'never exhausts past the cap when billing has no real limit',
            creditLimit: null,
            creditsUsed: STARTUP_CAP_CREDITS + 5_000,
            remaining: 0,
            exhausted: false,
        },
        {
            name: 'exhausts past the cap when billing has a real limit',
            creditLimit: STARTUP_CAP_CREDITS + 100_000,
            creditsUsed: STARTUP_CAP_CREDITS + 5_000,
            remaining: 0,
            exhausted: true,
        },
    ])('$name', ({ creditLimit, creditsUsed, remaining, exhausted }) => {
        const quota = makeQuota({ credit_limit: creditLimit, credits_used: creditsUsed, remaining: null })

        expect(applyStartupCap(quota, STARTUP_CAP_CREDITS)).toMatchObject({ remaining, exhausted })
    })
})
