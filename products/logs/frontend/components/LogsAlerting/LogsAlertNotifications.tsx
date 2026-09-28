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
    getHogFunctionEventKind,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_TEAMS,
    PendingLogsAlertNotification,
    resolveGroupLabel,
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

    const existingDestinations: AlertNotificationDestinationView[] = destinationGroups.map((group) => {
        const detailHogFunctionId =
            group.hogFunctions.find((hogFunction) => getHogFunctionEventKind(hogFunction) === 'firing')?.id ??
            group.hogFunctions[0]?.id
        const detailUrl =
            alertId && detailHogFunctionId ? urls.logsAlertNotificationDetail(alertId, detailHogFunctionId) : undefined

        return {
            key: group.key,
            title: resolveGroupLabel(group, slackChannels),
            tags: [{ label: group.enabled ? 'Active' : 'Paused', type: group.enabled ? 'success' : 'default' }],
            viewAction: {
                kind: 'button',
                label: 'View',
                url: detailUrl,
                disabledReason: detailUrl ? undefined : 'Save the alert to view details',
                dataAttr: 'logs-alert-destination-view',
            },
            onDelete: () => deleteExistingDestination(group),
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
                existingLoading: existingHogFunctionsLoading,
                existing: existingDestinations,
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
