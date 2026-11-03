import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import type { IntegrationType } from '~/types'

import { visionAlertsDestinationsCreate } from 'products/replay_vision/frontend/generated/api'

import { scannerAlertNotificationLogic } from './scannerAlertNotificationLogic'
import { VISION_ALERT_NOTIFICATION_TYPE_SLACK } from './scannerAlertUtils'

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
    let logic: ReturnType<typeof scannerAlertNotificationLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = undefined
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({ results: [] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const makeSlackIntegration = (id: number): IntegrationType => ({
        id,
        kind: 'slack',
        display_name: `Workspace ${id}`,
        icon_url: '',
        config: {},
        created_at: '2026-01-01T00:00:00Z',
    })

    it('stages a notification for the selected Slack workspace', async () => {
        logic = scannerAlertNotificationLogic({})
        logic.mount()
        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: 1,
            selectedSlackIntegration: firstWorkspace,
        })

        logic.actions.setSlackChannelValue('C123|#general')
        logic.actions.setSelectedSlackIntegrationId(2)
        await expectLogic(logic).toMatchValues({
            selectedSlackIntegration: secondWorkspace,
            slackChannelValue: null,
        })

        logic.actions.setSlackChannelValue('C456|#alerts')
        logic.actions.addSelectedNotification()

        await expectLogic(logic).toMatchValues({
            pendingNotifications: [
                {
                    type: VISION_ALERT_NOTIFICATION_TYPE_SLACK,
                    slackWorkspaceId: 2,
                    slackChannelId: 'C456',
                    slackChannelName: 'alerts',
                },
            ],
            slackChannelValue: null,
        })
    })

    it('keeps staged Slack state on reload only while its workspace is still connected', async () => {
        logic = scannerAlertNotificationLogic({})
        logic.mount()
        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])
        logic.actions.setSlackChannelValue('C123|#general')

        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: 1,
            slackChannelValue: 'C123|#general',
        })

        logic.actions.loadIntegrationsSuccess([secondWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegration: secondWorkspace,
            slackChannelValue: null,
        })

        logic.actions.setSlackChannelValue('C456|#alerts')
        logic.actions.addSelectedNotification()
        logic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://example.com/hook' })
        logic.actions.loadIntegrationsSuccess([firstWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegration: firstWorkspace,
            pendingNotifications: [{ type: 'webhook', webhookUrl: 'https://example.com/hook' }],
        })
    })

    it.each([
        ['an existing alert creates on add and points at Save to retry', 'alert-1', 'Save the alert to try again'],
        ['a new alert creates on submit and points at reopening', undefined, 'Reopen the alert'],
    ])('%s', async (_name, alertId, expectedToast) => {
        mockCreate.mockRejectedValueOnce(new Error('API error'))

        const alertLogic = scannerAlertNotificationLogic({ alertId })
        alertLogic.mount()

        await expectLogic(alertLogic, () => {
            alertLogic.actions.addPendingNotification({ type: 'webhook', webhookUrl: 'https://example.com/hook' })
            if (!alertId) {
                alertLogic.actions.createPendingHogFunctions('alert-1')
            }
        }).toFinishAllListeners()

        expect(mockCreate).toHaveBeenCalledTimes(1)
        expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining(expectedToast))
        expect(alertLogic.values.pendingNotifications).toHaveLength(1)

        alertLogic.unmount()
    })
})
