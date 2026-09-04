import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { visionAlertsList } from '../generated/api'
import { scannerAlertsLogic } from './scannerAlertsLogic'

jest.mock('posthog-js')
jest.mock('products/replay_vision/frontend/generated/api')

const mockAlertsList = visionAlertsList as jest.MockedFunction<typeof visionAlertsList>

const SCANNER_ID = '01a014ea-854f-72b5-8192-bb6ac9f212a5'

describe('scannerAlertsLogic', () => {
    let logic: ReturnType<typeof scannerAlertsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('separates a failed load from a scanner with no alerts', async () => {
        // Both leave the list empty. Reading a failure as "no alerts yet" tells the user their
        // alerts are gone, and leaves no way back but a page reload.
        mockAlertsList.mockRejectedValueOnce(new Error('boom'))
        logic = scannerAlertsLogic({ scannerId: SCANNER_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.alerts).toBeNull()
        expect(logic.values.alertsFailed).toBe(true)

        mockAlertsList.mockResolvedValueOnce({ results: [{ id: 'alert-1' }] } as any)
        logic.actions.loadAlerts()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.alertsFailed).toBe(false)
        expect(logic.values.alerts).toHaveLength(1)
    })

    it('holds the list null until the first load settles', async () => {
        mockAlertsList.mockResolvedValueOnce({ results: [] } as any)
        logic = scannerAlertsLogic({ scannerId: SCANNER_ID })
        logic.mount()

        expect(logic.values.alerts).toBeNull()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.alerts).toEqual([])
        expect(logic.values.alertsFailed).toBe(false)
    })
})
