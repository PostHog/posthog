import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import type { IntegrationType } from '~/types'

import { scannerAlertNotificationLogic } from './scannerAlertNotificationLogic'
import { VISION_ALERT_NOTIFICATION_TYPE_SLACK } from './scannerAlertUtils'

describe('scannerAlertNotificationLogic', () => {
    let logic: ReturnType<typeof scannerAlertNotificationLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = scannerAlertNotificationLogic({})
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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
        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: null,
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

    it('preserves the selected channel on reload unless its workspace was removed', async () => {
        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])
        logic.actions.setSlackChannelValue('C123|#general')

        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: null,
            selectedSlackIntegration: firstWorkspace,
            slackChannelValue: 'C123|#general',
        })

        logic.actions.setSelectedSlackIntegrationId(2)
        logic.actions.setSlackChannelValue('C456|#alerts')
        logic.actions.loadIntegrationsSuccess([firstWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: null,
            selectedSlackIntegration: firstWorkspace,
            slackChannelValue: null,
        })
    })
})
