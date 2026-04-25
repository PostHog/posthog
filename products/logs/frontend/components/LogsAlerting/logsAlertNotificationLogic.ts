import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionType, IntegrationType } from '~/types'

import { logsAlertsDestinationsCreate, logsAlertsDestinationsDeleteCreate } from 'products/logs/frontend/generated/api'

import type { logsAlertNotificationLogicType } from './logsAlertNotificationLogicType'
import {
    buildLogsAlertFilterConfig,
    groupLogsAlertDestinations,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
    LogsAlertDestinationGroup,
    LogsAlertNotificationType,
    PendingLogsAlertNotification,
} from './logsAlertUtils'

export const LOGS_ALERT_NOTIFICATION_TYPE_OPTIONS = [
    { label: 'Slack', value: LOGS_ALERT_NOTIFICATION_TYPE_SLACK },
    { label: 'Webhook', value: LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK },
]

export interface LogsAlertNotificationLogicProps {
    alertId?: string
}

export const logsAlertNotificationLogic = kea<logsAlertNotificationLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsAlerting', 'logsAlertNotificationLogic']),
    props({} as LogsAlertNotificationLogicProps),
    key(({ alertId }) => alertId ?? 'new'),

    connect({
        values: [projectLogic, ['currentProjectId'], integrationsLogic, ['slackIntegrations']],
        actions: [integrationsLogic, ['loadIntegrationsSuccess']],
    }),

    actions({
        addPendingNotification: (notification: PendingLogsAlertNotification) => ({ notification }),
        removePendingNotification: (index: number) => ({ index }),
        clearPendingNotifications: true,
        setPendingNotifications: (notifications: PendingLogsAlertNotification[]) => ({ notifications }),
        deleteExistingDestination: (group: LogsAlertDestinationGroup) => ({ group }),
        createPendingHogFunctions: (alertId: string) => ({ alertId }),
        setSelectedType: (selectedType: LogsAlertNotificationType) => ({ selectedType }),
        setSlackChannelValue: (slackChannelValue: string | null) => ({ slackChannelValue }),
        setWebhookUrl: (webhookUrl: string) => ({ webhookUrl }),
    }),

    reducers({
        pendingNotifications: [
            [] as PendingLogsAlertNotification[],
            {
                addPendingNotification: (state, { notification }) => [...state, notification],
                removePendingNotification: (state, { index }) => state.filter((_, i) => i !== index),
                clearPendingNotifications: () => [],
                setPendingNotifications: (_, { notifications }) => notifications,
            },
        ],
        slackChannelValue: [
            null as string | null,
            {
                setSlackChannelValue: (_, { slackChannelValue }) => slackChannelValue,
            },
        ],
        webhookUrl: [
            '' as string,
            {
                setWebhookUrl: (_, { webhookUrl }) => webhookUrl,
            },
        ],
        selectedType: [
            LOGS_ALERT_NOTIFICATION_TYPE_SLACK as LogsAlertNotificationType,
            {
                setSelectedType: (_, { selectedType }) => selectedType,
            },
        ],
    }),

    loaders(({ props }) => ({
        existingHogFunctions: [
            [] as HogFunctionType[],
            {
                loadExistingHogFunctions: async (alertId?: string) => {
                    const id = alertId ?? props.alertId
                    if (!id) {
                        return []
                    }
                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: [buildLogsAlertFilterConfig(id)],
                        full: true,
                    })
                    return response.results
                },
            },
        ],
    })),

    selectors({
        firstSlackIntegration: [
            (s) => [s.slackIntegrations],
            (slackIntegrations: IntegrationType[] | undefined): IntegrationType | undefined => slackIntegrations?.[0],
        ],
        // Channel-name resolution happens in the view — slackChannels lives in a dynamically-keyed logic.
        destinationGroups: [
            (s) => [s.existingHogFunctions],
            (hogFunctions: HogFunctionType[]): LogsAlertDestinationGroup[] =>
                groupLogsAlertDestinations(hogFunctions, () => null),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        addPendingNotification: () => {
            if (props.alertId) {
                actions.createPendingHogFunctions(props.alertId)
            }
        },
        loadIntegrationsSuccess: () => {
            if (!values.firstSlackIntegration) {
                actions.setSelectedType(LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK)
            }
        },
        deleteExistingDestination: async ({ group }) => {
            if (!props.alertId) {
                return
            }
            try {
                await logsAlertsDestinationsDeleteCreate(String(values.currentProjectId), props.alertId, {
                    hog_function_ids: group.hogFunctions.map((hf) => hf.id),
                })
                lemonToast.success(`Removed ${group.label}`)
                actions.loadExistingHogFunctions()
            } catch {
                lemonToast.error(`Failed to remove ${group.label}`)
                actions.loadExistingHogFunctions()
            }
        },

        createPendingHogFunctions: async ({ alertId }) => {
            const pending = values.pendingNotifications
            if (pending.length === 0) {
                return
            }

            const projectId = String(values.currentProjectId)
            const results = await Promise.allSettled(
                pending.map((notification) => {
                    const payload =
                        notification.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK
                            ? {
                                  type: LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
                                  slack_workspace_id: notification.slackWorkspaceId,
                                  slack_channel_id: notification.slackChannelId,
                                  slack_channel_name: notification.slackChannelName,
                              }
                            : {
                                  type: LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
                                  webhook_url: notification.webhookUrl,
                              }
                    return logsAlertsDestinationsCreate(projectId, alertId, payload)
                })
            )

            const failedNotifications = pending.filter((_, i) => results[i].status === 'rejected')

            if (failedNotifications.length > 0) {
                lemonToast.error(
                    `Alert saved, but ${failedNotifications.length} notification(s) failed to create. Reopen the alert to add them again.`
                )
                actions.setPendingNotifications(failedNotifications)
            } else {
                if (pending.length > 0) {
                    lemonToast.success(`${pending.length} notification destination(s) created.`)
                }
                actions.clearPendingNotifications()
            }

            actions.loadExistingHogFunctions(alertId)
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.alertId) {
            actions.loadExistingHogFunctions()
        }
    }),
])
