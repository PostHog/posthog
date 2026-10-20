import { expectLogic } from 'kea-test-utils'

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
})
