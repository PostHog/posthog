import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeQuota } from '../utils/quotaTestUtils'
import { visionQuotaLogic } from './visionQuotaLogic'

const quota = makeQuota({
    monthly_quota: 1000,
    usage_this_month: 100,
    remaining: 900,
    projected_monthly_observations: 500,
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
        expect(logic.values.quota?.projected_monthly_observations).toBe(750)

        logic.actions.adjustProjectedMonthly(-10_000)
        expect(logic.values.quota?.projected_monthly_observations).toBe(0)
    })

    it('adjustProjectedMonthly is a no-op before the quota has loaded', () => {
        logic.actions.adjustProjectedMonthly(250)
        expect(logic.values.quota).toBeNull()
    })

    it('loadQuota overwrites any optimistic adjustment with the server value', async () => {
        await expectLogic(logic).toDispatchActions(['loadQuotaSuccess'])
        logic.actions.adjustProjectedMonthly(250)

        await expectLogic(logic, () => logic.actions.loadQuota()).toDispatchActions(['loadQuotaSuccess'])

        expect(logic.values.quota?.projected_monthly_observations).toBe(500)
    })
})
