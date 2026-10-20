import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { platformAlertsList } from 'products/alerts_platform/frontend/generated/api'

import { alertTriggerOptionsLogic } from './alertTriggerOptionsLogic'

jest.mock('products/alerts_platform/frontend/generated/api', () => ({
    __esModule: true,
    platformAlertsList: jest.fn(),
}))

const mockList = platformAlertsList as jest.MockedFunction<typeof platformAlertsList>

describe('alertTriggerOptionsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it('offers every page of alerts, not only the first', async () => {
        const alert = (id: string): any => ({ id, name: id })
        mockList
            .mockResolvedValueOnce({ count: 3, next: 'page-2', results: [alert('a'), alert('b')] } as any)
            .mockResolvedValueOnce({ count: 3, next: null, results: [alert('c')] } as any)

        const logic = alertTriggerOptionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.alerts?.map((a) => a.id)).toEqual(['a', 'b', 'c'])
        expect(mockList.mock.calls.map((call) => call[1]?.offset)).toEqual([0, 100])
        logic.unmount()
    })

    it('stops paging once the panel closes', async () => {
        let releaseFirstPage: (page: any) => void = () => {}
        mockList.mockImplementationOnce(() => new Promise((resolve) => (releaseFirstPage = resolve)))

        const logic = alertTriggerOptionsLogic()
        logic.mount()
        logic.unmount()
        releaseFirstPage({ count: 3, next: 'page-2', results: [{ id: 'a', name: 'a' }] })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(mockList).toHaveBeenCalledTimes(1)
    })

    it('offers no alerts outside the main environment, without asking the API', async () => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...teamLogic.values.currentTeam!, id: 999, project_id: 1 } as any)

        const logic = alertTriggerOptionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.inMainEnvironment).toBe(false)
        expect(logic.values.alerts).toEqual([])
        expect(mockList).not.toHaveBeenCalled()
        logic.unmount()
    })
})
