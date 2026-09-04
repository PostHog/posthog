import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { VISION_ALERT_NOTIFICATION_TYPE_OPTIONS, scannerAlertNotificationLogic } from '../scannerAlertNotificationLogic'
import { PendingVisionAlertNotification, VISION_ALERT_NOTIFICATION_TYPE_SLACK } from '../scannerAlertUtils'

function pendingDestinationView(notification: PendingVisionAlertNotification): {
    title: string
    detail?: string
} {
    if (notification.type === VISION_ALERT_NOTIFICATION_TYPE_SLACK) {
        return { title: 'Slack', detail: `#${notification.slackChannelName ?? 'channel'}` }
    }
    return { title: 'Webhook', detail: notification.webhookUrl }
}

export function ScannerAlertNotifications(): JSX.Element {
    const {
        existingHogFunctionsLoading,
        destinationGroups,
        pendingNotifications,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        firstSlackIntegration,
        selectedType,
        slackChannelValue,
        webhookUrl,
        urlInput,
        addDisabledReason,
    } = useValues(scannerAlertNotificationLogic)
    const {
        addSelectedNotification,
        removePendingNotification,
        deleteExistingDestination,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
        loadIntegrations,
    } = useActions(scannerAlertNotificationLogic)

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { loadAllSlackChannels } = useActions(slackLogic)
    useEffect(() => {
        if (firstSlackIntegration?.id) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels])

    const existingDestinations: AlertNotificationDestinationView[] = destinationGroups.map((group) => ({
        key: group.key,
        title: group.label,
        tags: group.enabled ? undefined : [{ label: 'Disabled' }],
        onDelete: () => deleteExistingDestination(group),
        deleting: false,
    }))
    const pendingDestinations: PendingAlertNotificationDestinationView[] = pendingNotifications.map(
        (notification, index) => ({
            key: `${notification.type}-${index}`,
            ...pendingDestinationView(notification),
            onRemove: () => removePendingNotification(index),
        })
    )

    return (
        <AlertNotificationDestinationEditor
            description="Each destination receives every notification this alert sends."
            destinations={{
                showExisting: true,
                existingLoading: existingHogFunctionsLoading,
                existing: existingDestinations,
                pending: pendingDestinations,
            }}
            notificationType={{
                options: VISION_ALERT_NOTIFICATION_TYPE_OPTIONS,
                value: selectedType,
                onChange: setSelectedType,
            }}
            slack={{
                notificationType: VISION_ALERT_NOTIFICATION_TYPE_SLACK,
                integrationsLoading,
                integrationsFailed,
                onRetryIntegrations: loadIntegrations,
                integrations: slackIntegrations,
                integration: firstSlackIntegration,
                channelValue: slackChannelValue,
                onChannelValueChange: setSlackChannelValue,
            }}
            url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
            add={{ onClick: addSelectedNotification, disabledReason: addDisabledReason }}
        />
    )
}
