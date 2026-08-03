import { expectLogic } from 'kea-test-utils'

import { billingLogic } from 'scenes/billing/billingLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType, StartupProgramLabel } from '~/types'

import { makeQuota } from '../utils/quotaTestUtils'
import { STARTUP_CAP_CREDITS } from '../utils/startupCap'
import { visionQuotaLogic } from './visionQuotaLogic'

const quota = makeQuota({
    credit_limit: 1000,
    credits_used: 100,
    remaining: 900,
    projected_monthly_credits: 500,
})

describe('visionQuotaLogic', () => {
    let logic: ReturnType<typeof visionQuotaLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/quota/': quota,
            },
        })
        initKeaTests()
        logic = visionQuotaLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('adjustProjectedMonthly shifts the loaded projection and clamps at zero', async () => {
        await expectLogic(logic).toDispatchActions(['loadQuotaSuccess'])

        logic.actions.adjustProjectedMonthly(250)
        expect(logic.values.quota?.projected_monthly_credits).toBe(750)

        logic.actions.adjustProjectedMonthly(-10_000)
        expect(logic.values.quota?.projected_monthly_credits).toBe(0)
    })

    it('adjustProjectedMonthly is a no-op before the quota has loaded', () => {
        logic.actions.adjustProjectedMonthly(250)
        expect(logic.values.quota).toBeNull()
    })

    it('derives billing display values from the quota, paid vs free-allocation-only', async () => {
        await expectLogic(logic).toDispatchActions(['loadQuotaSuccess'])

        // Paid org: 4,000 used against a 10,000 limit with a 2,500 free tier.
        logic.actions.loadQuotaSuccess(makeQuota({ credits_used: 4000, remaining: 6000 }))
        expect(logic.values.showUsd).toBe(true)
        expect(logic.values.onFreePlan).toBe(false)
        expect(logic.values.billedCredits).toBe(1500)
        expect(logic.values.billedLimitCredits).toBe(7500)

        // Free-allocation-only org: the whole limit is the free tier, so nothing bills.
        logic.actions.loadQuotaSuccess(makeQuota({ credit_limit: 2500, credits_used: 1000, remaining: 1500 }))
        expect(logic.values.showUsd).toBe(false)
        expect(logic.values.onFreePlan).toBe(true)
        expect(logic.values.billedCredits).toBe(0)
        expect(logic.values.billedLimitCredits).toBe(0)
    })

    it('loadQuota overwrites any optimistic adjustment with the server value', async () => {
        await expectLogic(logic).toDispatchActions(['loadQuotaSuccess'])
        logic.actions.adjustProjectedMonthly(250)

        await expectLogic(logic, () => logic.actions.loadQuota()).toDispatchActions(['loadQuotaSuccess'])

        expect(logic.values.quota?.projected_monthly_credits).toBe(500)
    })
})
