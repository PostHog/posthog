import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { VISION_ALERT_NOTIFICATION_TYPE_OPTIONS, scannerAlertNotificationLogic } from '../scannerAlertNotificationLogic'
import { VISION_ALERT_NOTIFICATION_TYPE_SLACK, pendingVisionAlertNotificationView } from '../scannerAlertUtils'

export function ScannerAlertNotifications(): JSX.Element {
    const {
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

    const slackLogic = slackIntegrationLogic({ id: selectedSlackIntegration?.id ?? 0 })
    const { loadAllSlackChannels } = useActions(slackLogic)
    useEffect(() => {
        if (selectedSlackIntegration?.id) {
            loadAllSlackChannels()
        }
    }, [selectedSlackIntegration?.id, loadAllSlackChannels])

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
