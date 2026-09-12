import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAlertsDestinationsUpdate, logsAlertsRetrieve } from 'products/logs/frontend/generated/api'

import { logsAlertNotificationDetailSceneLogic } from '../logsAlertNotificationDetailSceneLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        hogFunctions: { list: jest.fn() },
        integrations: { list: jest.fn().mockResolvedValue({ results: [] }) },
    },
}))

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsDestinationsDeleteCreate: jest.fn(),
    logsAlertsDestinationsUpdate: jest.fn(),
    logsAlertsRetrieve: jest.fn(),
}))

const mockApi = require('lib/api').default
const mockDestinationUpdate = logsAlertsDestinationsUpdate as jest.MockedFunction<typeof logsAlertsDestinationsUpdate>
const mockAlertRetrieve = logsAlertsRetrieve as jest.MockedFunction<typeof logsAlertsRetrieve>

const ALERT_ID = 'alert-1'
const FIRING_HOG_FUNCTION = {
    id: 'hf-firing',
    name: 'Logs alert (firing)',
    type: 'internal_destination',
    template_id: 'template-webhook',
    enabled: true,
    inputs: { url: { value: 'https://example.com/hook' } },
    filters: {
        events: [{ id: '$logs_alert_firing', type: 'events' }],
        properties: [{ key: 'alert_id', value: ALERT_ID, operator: 'exact', type: 'event' }],
    },
} as any

describe('logsAlertNotificationDetailSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockAlertRetrieve.mockResolvedValue({ id: ALERT_ID, name: 'Logs alert' } as any)
        mockDestinationUpdate.mockResolvedValue(undefined)
        mockApi.hogFunctions.list.mockResolvedValue({ results: [FIRING_HOG_FUNCTION] })
    })

    it('updates a lifecycle toggle through the logs alert API', async () => {
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: ALERT_ID, hogFunctionId: 'hf-firing' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setHogFunctionEnabled('hf-firing', false)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockDestinationUpdate).toHaveBeenCalledWith(expect.any(String), ALERT_ID, 'hf-firing', {
            enabled: false,
        })
        expect(mockApi.hogFunctions.update).toBeUndefined()
        expect(mockApi.hogFunctions.list).toHaveBeenCalledTimes(3)

        logic.unmount()
    })
})
