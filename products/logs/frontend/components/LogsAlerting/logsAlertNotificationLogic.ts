import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { projectLogic } from 'scenes/projectLogic'

import { HogFunctionType, IntegrationType } from '~/types'

import type { logsAlertNotificationLogicType } from './logsAlertNotificationLogicType'
import {
    buildLogsAlertFilterConfig,
    buildLogsAlertHogFunctionPayload,
    LOGS_ALERT_NOTIFICATION_TYPE_SLACK,
    LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK,
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
        deleteExistingHogFunction: (hogFunction: HogFunctionType) => ({ hogFunction }),
        createPendingHogFunctions: (alertId: string, alertName?: string) => ({ alertId, alertName }),
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
        existingHogFunctions: [
            [] as HogFunctionType[],
            {
                deleteExistingHogFunction: (state, { hogFunction }) => state.filter((hf) => hf.id !== hogFunction.id),
            },
        ],
    }),

    selectors({
        firstSlackIntegration: [
            (s) => [s.slackIntegrations],
            (slackIntegrations: IntegrationType[] | undefined): IntegrationType | undefined => slackIntegrations?.[0],
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

    listeners(({ actions, values }) => ({
        loadIntegrationsSuccess: () => {
            if (!values.firstSlackIntegration) {
                actions.setSelectedType(LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK)
            }
        },
        deleteExistingHogFunction: async ({ hogFunction }) => {
            await deleteWithUndo({
                endpoint: `projects/${values.currentProjectId}/hog_functions`,
                object: {
                    id: hogFunction.id,
                    name: hogFunction.name,
                },
                callback: (undo) => {
                    if (undo) {
                        actions.loadExistingHogFunctions()
                    }
                },
            })
        },

        createPendingHogFunctions: async ({ alertId, alertName }) => {
            const pending = values.pendingNotifications
            if (pending.length === 0) {
                return
            }

            const results = await Promise.allSettled(
                pending.map((notification) => {
                    const payload = buildLogsAlertHogFunctionPayload(alertId, alertName, notification)
                    return api.hogFunctions.create(payload)
                })
            )

            const failedNotifications = pending.filter((_, i) => results[i].status === 'rejected')

            if (failedNotifications.length > 0) {
                lemonToast.error(
                    `Alert saved, but ${failedNotifications.length} notification(s) failed to create. Reopen the alert to add them again.`
                )
                actions.setPendingNotifications(failedNotifications)
            } else {
                if (results.length > 0) {
                    lemonToast.success(`${results.length} notification destination(s) created.`)
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
