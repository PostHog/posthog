import { useActions, useValues } from 'kea'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { VISION_ALERT_NOTIFICATION_TYPE_OPTIONS, scannerAlertNotificationLogic } from '../scannerAlertNotificationLogic'
import { VISION_ALERT_NOTIFICATION_TYPE_SLACK, pendingVisionAlertNotificationView } from '../scannerAlertUtils'

export function ScannerAlertNotifications(): JSX.Element {
    const {
        autoSavesDestinations,
        existingHogFunctionsLoading,
        destinationGroups,
        pendingNotifications,
        integrationsLoading,
        integrationsFailed,
        slackIntegrations,
        selectedSlackIntegration,
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
        setSelectedSlackIntegrationId,
        setSlackChannelValue,
        setWebhookUrl,
        loadIntegrations,
    } = useActions(scannerAlertNotificationLogic)

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
            ...pendingVisionAlertNotificationView(notification, slackIntegrations),
            onRemove: () => removePendingNotification(index),
        })
    )

    return (
        <AlertNotificationDestinationEditor
            description={
                autoSavesDestinations
                    ? 'Each destination receives every notification this alert sends. Added and removed destinations save automatically.'
                    : 'Each destination receives every notification this alert sends.'
            }
            destinations={{
                showExisting: true,
                existingLoading: existingHogFunctionsLoading,
                existing: existingDestinations,
                pending: pendingDestinations,
                pendingTooltip: autoSavesDestinations
                    ? 'Not added yet. If it stays pending, save the alert to add it.'
                    : undefined,
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
                integration: selectedSlackIntegration,
                onIntegrationChange: setSelectedSlackIntegrationId,
                channelValue: slackChannelValue,
                onChannelValueChange: setSlackChannelValue,
            }}
            url={urlInput ? { input: urlInput, value: webhookUrl, onChange: setWebhookUrl } : undefined}
            add={{ onClick: addSelectedNotification, disabledReason: addDisabledReason }}
        />
    )
}
