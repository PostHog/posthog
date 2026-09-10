import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'

import { newSubscriptionTargetLogic } from './newSubscriptionTargetLogic'

describe('newSubscriptionTargetLogic', () => {
    let logic: ReturnType<typeof newSubscriptionTargetLogic.build>
    let dashboardSpy: jest.SpyInstance

    beforeEach(() => {
        dashboardSpy = jest.spyOn(api.dashboards, 'get')
        initKeaTests()
        logic = newSubscriptionTargetLogic()
        logic.mount()
    })

    afterEach(() => {
        dashboardSpy.mockRestore()
        logic.unmount()
    })

    // The creation form needs the dashboard's tiles to offer its insights, so a target picked
    // without that fetch leaves the modal with nothing to render.
    it('fetches the dashboard a target was picked from', async () => {
        dashboardSpy.mockResolvedValue({ id: 7, name: 'Weekly review', tiles: [] } as unknown as DashboardType)

        logic.actions.chooseDashboard(7, 'Weekly review')
        await expectLogic(logic).toFinishAllListeners()

        expect(dashboardSpy).toHaveBeenCalledWith(7)
        expect(logic.values.target).toEqual({ kind: 'dashboard', id: 7, name: 'Weekly review' })
        expect(logic.values.dashboard).toMatchObject({ id: 7 })
    })

    it('drops the target when the dashboard cannot be loaded', async () => {
        dashboardSpy.mockRejectedValue(new Error('gone'))

        logic.actions.chooseDashboard(7, 'Weekly review')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.target).toBeNull()
        expect(logic.values.dashboard).toBeNull()
    })
})
