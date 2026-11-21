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
        ;(logsAlertsRetrieve as jest.Mock).mockResolvedValue({
            destinations: [
                { id: null, hog_function_ids: ['fn-firing', 'fn-resolved'] },
                { id: null, hog_function_ids: ['fn-other'] },
            ],
        })
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

    it('asks for the sends of a secret-URL group only once the alert lists its functions', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ALERTS_DESTINATION_CUSTOMIZATION]: true })
        mockList.mockResolvedValue({
            results: ['fn-firing', 'fn-resolved'].map((id) => ({
                ...webhookFunction(id, '$logs_alert_firing'),
                inputs: { url: { secret: true } },
            })),
        })
        let releaseAlert: (alert: unknown) => void = () => {}
        ;(logsAlertsRetrieve as jest.Mock).mockReturnValue(new Promise((resolve) => (releaseAlert = resolve)))
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadHogFunctions()).toDispatchActions(['loadHogFunctionsSuccess'])
        expect(mockSends).not.toHaveBeenCalled()

        releaseAlert({ destinations: [{ id: null, hog_function_ids: ['fn-firing', 'fn-resolved'] }] })
        await expectLogic(logic).toFinishAllListeners()

        expect(mockSends.mock.calls.map(([, , params]) => params.hog_function_ids)).toEqual([
            ['fn-firing', 'fn-resolved'],
        ])
    })

    it.each([
        ['is pending', (): Promise<unknown> => new Promise(() => {})],
        ['failed', (): Promise<unknown> => Promise.reject(new Error('boom'))],
    ])('offers no destination to remove while the alert %s', async (_name, alertResponse) => {
        ;(logsAlertsRetrieve as jest.Mock).mockImplementation(alertResponse)
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadHogFunctions()).toDispatchActions(['loadHogFunctionsSuccess'])

        expect(logic.values.destinationGroup).toBeNull()
    })

    it('treats the alert as unsettled again while a retry after a failed load runs', async () => {
        ;(logsAlertsRetrieve as jest.Mock).mockImplementation(() => Promise.reject(new Error('boom')))
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.alertSettled).toBe(true)

        ;(logsAlertsRetrieve as jest.Mock).mockImplementation(() => new Promise(() => {}))
        logic.actions.loadAlert()

        expect(logic.values.alertSettled).toBe(false)
    })

    it.each([
        ['splits a URL group the alert lists apart', false, [['fn-firing'], ['fn-resolved']], ['fn-resolved']],
        ['joins functions whose URL is secret', true, [['fn-firing', 'fn-resolved']], ['fn-firing', 'fn-resolved']],
    ])('keeps to the functions the alert lists as this destination: %s', async (_name, secret, listed, expected) => {
        if (secret) {
            mockList.mockResolvedValue({
                results: ['fn-firing', 'fn-resolved'].map((id) => ({
                    ...webhookFunction(id, '$logs_alert_firing'),
                    inputs: { url: { secret: true } },
                })),
            })
        }
        ;(logsAlertsRetrieve as jest.Mock).mockResolvedValue({
            destinations: listed.map((ids) => ({ id: null, hog_function_ids: ids })),
        })
        const logic = logsAlertNotificationDetailSceneLogic({ alertId: 'alert-1', hogFunctionId: 'fn-resolved' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.destinationGroup?.hogFunctions.map((hogFunction) => hogFunction.id)).toEqual(expected)
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
