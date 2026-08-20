import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { slackIntegrationLogic } from 'lib/integrations/slackIntegrationLogic'
import { urls } from 'scenes/urls'

import {
    AlertNotificationDestinationEditor,
    AlertNotificationDestinationView,
    PendingAlertNotificationDestinationView,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'

import { LOGS_ALERT_NOTIFICATION_TYPE_OPTIONS, logsAlertNotificationLogic } from './logsAlertNotificationLogic'
import {
    destinationLabel,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_TEAMS,
    PendingLogsAlertNotification,
} from './logsAlertUtils'

function getPendingNotificationDestination(
    notification: PendingLogsAlertNotification
): Pick<PendingAlertNotificationDestinationView, 'title' | 'detail'> {
    if (notification.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK) {
        return { title: 'Slack', detail: `#${notification.slackChannelName ?? 'channel'}` }
    }
    if (notification.type === LOGS_ALERT_NOTIFICATION_TYPE_TEAMS) {
        return { title: 'Microsoft Teams', detail: notification.webhookUrl }
    }
    return { title: 'Webhook', detail: notification.webhookUrl }
}

export function LogsAlertNotifications({ alertId }: { alertId?: string }): JSX.Element {
    const {
        existingDestinationsLoading,
        existingDestinations,
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
    } = useValues(logsAlertNotificationLogic)
    const {
        addSelectedNotification,
        removePendingNotification,
        deleteExistingDestination,
        setSelectedType,
        setSlackChannelValue,
        setWebhookUrl,
        loadIntegrations,
    } = useActions(logsAlertNotificationLogic)

    const slackLogic = slackIntegrationLogic({ id: firstSlackIntegration?.id ?? 0 })
    const { slackChannels } = useValues(slackLogic)
    const { loadAllSlackChannels } = useActions(slackLogic)

    useEffect(() => {
        if (firstSlackIntegration) {
            loadAllSlackChannels()
        }
    }, [firstSlackIntegration?.id, loadAllSlackChannels, firstSlackIntegration])

    const slackLookup = { workspaceId: firstSlackIntegration?.id, channels: slackChannels }

    const destinationViews: AlertNotificationDestinationView[] = existingDestinations.map((destination) => {
        // Any id in the group resolves to the same destination on the detail scene.
        const detailHogFunctionId = destination.hog_function_ids[0]
        const detailUrl =
            alertId && detailHogFunctionId ? urls.logsAlertNotificationDetail(alertId, detailHogFunctionId) : undefined
        const label = destinationLabel(destination, slackLookup)

        return {
            key: destination.hog_function_ids.join('|'),
            title: label,
            tags: [
                {
                    label: destination.enabled ? 'Active' : 'Paused',
                    type: destination.enabled ? 'success' : 'default',
                },
            ],
            viewAction: {
                kind: 'button',
                label: 'View',
                url: detailUrl,
                disabledReason: detailUrl ? undefined : 'Save the alert to view details',
                dataAttr: 'logs-alert-destination-view',
            },
            onDelete: () => deleteExistingDestination(destination, label),
        }
    })

    const pendingDestinations: PendingAlertNotificationDestinationView[] = pendingNotifications.map(
        (notification, index) => ({
            key: `${notification.type}-${index}`,
            ...getPendingNotificationDestination(notification),
            onRemove: () => removePendingNotification(index),
        })
    )

    return (
        <AlertNotificationDestinationEditor
            description="Each destination delivers notifications for all alert events: firing, resolved, and broken."
            destinations={{
                showExisting: true,
                existingLoading: existingDestinationsLoading,
                existing: destinationViews,
                pending: pendingDestinations,
            }}
            notificationType={{
                options: LOGS_ALERT_NOTIFICATION_TYPE_OPTIONS,
                value: selectedType,
                onChange: setSelectedType,
            }}
            slack={{
                notificationType: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
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
