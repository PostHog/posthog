import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { logsAlertsDestinationsSendsList, logsAlertsRetrieve } from 'products/logs/frontend/generated/api'

import { logsAlertNotificationDetailSceneLogic } from '../logsAlertNotificationDetailSceneLogic'

jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        ...actual,
        __esModule: true,
        default: { ...actual.default, hogFunctions: { list: jest.fn() } },
    }
})

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAlertsDestinationsDeleteCreate: jest.fn(),
    logsAlertsDestinationsSendsList: jest.fn(),
    logsAlertsRetrieve: jest.fn(),
}))

const mockList = api.hogFunctions.list as jest.Mock
const mockSends = logsAlertsDestinationsSendsList as jest.MockedFunction<typeof logsAlertsDestinationsSendsList>

function webhookFunction(id: string, event: string): HogFunctionType {
    return {
        id,
        name: id,
        enabled: true,
        template_id: 'template-webhook',
        inputs: { url: { value: 'https://example.com/hook' } },
        filters: { events: [{ id: event, type: 'events' }] },
    } as unknown as HogFunctionType
}

describe('logsAlertNotificationDetailSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        ;(logsAlertsRetrieve as jest.Mock).mockResolvedValue(null)
        mockList.mockResolvedValue({
            results: [
                webhookFunction('fn-firing', '$logs_alert_firing'),
                webhookFunction('fn-resolved', '$logs_alert_resolved'),
                {
                    ...webhookFunction('fn-other', '$logs_alert_firing'),
                    inputs: { url: { value: 'https://example.com/other' } },
                },
            ],
        })
        mockSends.mockResolvedValue([])
    })

    it.each([
        [true, [['fn-firing', 'fn-resolved']]],
        [false, []],
    ])('asks for the sends of the whole group only behind the flag (flag on: %s)', async (flagOn, expected) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ALERTS_DESTINATION_CUSTOMIZATION]: flagOn })
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockSends.mock.calls.map(([, , params]) => params.hog_function_ids)).toEqual(expected)
    })

    it('loads the sends when the flag turns on after the functions loaded', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockSends).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ALERTS_DESTINATION_CUSTOMIZATION]: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSends.mock.calls.map(([, , params]) => params.hog_function_ids)).toEqual([
            ['fn-firing', 'fn-resolved'],
        ])
    })
})
