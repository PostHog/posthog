import { HogFunctionType, IntegrationType } from '~/types'

import {
    PendingVisionAlertNotification,
    VISION_ALERT_NOTIFICATION_TYPE_SLACK,
    alertTagOptions,
    groupVisionAlertDestinations,
    pendingVisionAlertNotificationView,
} from './scannerAlertUtils'

describe('scannerAlertUtils', () => {
    describe('alertTagOptions', () => {
        it('keeps the configured categories first and in configuration order', () => {
            expect(alertTagOptions(['checkout', 'onboarding'], ['analytics'])).toEqual([
                { key: 'checkout', label: 'checkout' },
                { key: 'onboarding', label: 'onboarding' },
                { key: 'analytics', label: 'analytics', tooltip: 'Freeform tag seen in observations' },
            ])
        })

        it('does not repeat a configured category that observations also carried', () => {
            expect(alertTagOptions(['checkout', 'checkout'], ['checkout', 'rage'])).toEqual([
                { key: 'checkout', label: 'checkout' },
                { key: 'rage', label: 'rage', tooltip: 'Freeform tag seen in observations' },
            ])
        })

        it('returns nothing when the scanner has no tags at all', () => {
            expect(alertTagOptions([], [])).toEqual([])
        })
    })

    it('keeps the same Slack channel in different workspaces as separate destinations', () => {
        const slackHogFunction = (id: string, workspaceId: number): HogFunctionType =>
            ({
                id,
                name: `slack-${id}`,
                enabled: true,
                template_id: 'template-slack',
                inputs: {
                    slack_workspace: { value: workspaceId },
                    channel: { value: 'C123' },
                },
            }) as unknown as HogFunctionType

        const groups = groupVisionAlertDestinations([
            slackHogFunction('hf-workspace-1-firing', 1),
            slackHogFunction('hf-workspace-1-resolved', 1),
            slackHogFunction('hf-workspace-2', 2),
        ])

        expect(groups.map(({ key }) => key)).toEqual(['slack:1:C123', 'slack:2:C123'])
        expect(groups).toHaveLength(2)
        expect(groups.map(({ hogFunctions }) => hogFunctions.length)).toEqual([2, 1])
    })

    it('includes the Slack workspace name in a pending destination', () => {
        const notification: PendingVisionAlertNotification = {
            type: VISION_ALERT_NOTIFICATION_TYPE_SLACK,
            slackWorkspaceId: 2,
            slackChannelId: 'C123',
            slackChannelName: 'alerts',
        }
        const integrations = [
            { id: 1, display_name: 'Workspace one' },
            { id: 2, display_name: 'Workspace two' },
        ] as IntegrationType[]

        expect(pendingVisionAlertNotificationView(notification, integrations)).toEqual({
            title: 'Slack',
            detail: 'Workspace two · #alerts',
        })
    })
})
