import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { aeoPromptsCreateDashboard } from '../generated/api'
import { contentAutopilotVisibilityDashboardLogic } from './contentAutopilotVisibilityDashboardLogic'

jest.mock('../generated/api', () => ({
    aeoPromptsCreateDashboard: jest.fn(),
}))

describe('contentAutopilotVisibilityDashboardLogic', () => {
    let logic: ReturnType<typeof contentAutopilotVisibilityDashboardLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast')
        jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast')
        logic = contentAutopilotVisibilityDashboardLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the new dashboard and offers a weekly subscription to it', async () => {
        jest.mocked(aeoPromptsCreateDashboard).mockResolvedValue({ id: 42, name: 'AI visibility weekly' })

        await expectLogic(logic, () => logic.actions.createVisibilityDashboard())
            .toDispatchActions(['createVisibilityDashboard', 'createVisibilityDashboardFinished'])
            .toMatchValues({ creatingVisibilityDashboard: false })

        expect(router.values.location.pathname).toContain(urls.dashboard(42))
        const button = jest.mocked(lemonToast.success).mock.calls[0][1]?.button
        button?.action?.()
        expect(router.values.location.pathname).toContain(urls.dashboardSubscription(42, 'new'))
    })

    it('reports a failure and lets the person try again', async () => {
        jest.mocked(aeoPromptsCreateDashboard).mockRejectedValue({
            detail: 'Creating a dashboard requires dashboard edit access.',
        })

        await expectLogic(logic, () => logic.actions.createVisibilityDashboard())
            .toDispatchActions(['createVisibilityDashboard', 'createVisibilityDashboardFinished'])
            .toMatchValues({ creatingVisibilityDashboard: false })

        expect(lemonToast.error).toHaveBeenCalledWith(
            "Couldn't create the dashboard: Creating a dashboard requires dashboard edit access."
        )
    })
})
