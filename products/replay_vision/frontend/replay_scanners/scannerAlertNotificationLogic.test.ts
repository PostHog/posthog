import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { visionAlertsDestinationsCreate } from 'products/replay_vision/frontend/generated/api'

import { scannerAlertNotificationLogic } from './scannerAlertNotificationLogic'

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        ...actual,
        __esModule: true,
        default: { ...actual.default, hogFunctions: { list: jest.fn() } },
    }
})

jest.mock('products/replay_vision/frontend/generated/api', () => ({
    __esModule: true,
    visionAlertsDestinationsCreate: jest.fn(),
    visionAlertsDestinationsDeleteCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockApi = api as jest.Mocked<typeof api>
const mockCreate = visionAlertsDestinationsCreate as jest.MockedFunction<typeof visionAlertsDestinationsCreate>

describe('scannerAlertNotificationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({ results: [] })
    })

    it.each([
        ['an existing alert creates on add and points at Save to retry', 'alert-1', 'Save the alert to try again'],
        ['a new alert creates on submit and points at reopening', undefined, 'Reopen the alert'],
    ])('%s', async (_name, alertId, expectedToast) => {
        mockCreate.mockRejectedValueOnce(new Error('API error'))

        const logic = scannerAlertNotificationLogic({ alertId })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://example.com/hook' })
            if (!alertId) {
                logic.actions.createPendingHogFunctions('alert-1')
            }
        }).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining(expectedToast))
        expect(logic.values.pendingNotifications).toHaveLength(1)

        logic.unmount()
    })
})
