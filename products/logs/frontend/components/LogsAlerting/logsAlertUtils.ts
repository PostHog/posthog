import { LOGS_ALERT_FIRING_EVENT_ID, LOGS_ALERT_FIRING_SUB_TEMPLATE_ID } from 'lib/constants'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

export const LOGS_ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export type LogsAlertNotificationType =
    | typeof LOGS_ALERT_NOTIFICATION_TYPE_SLACK
    | typeof LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK

export type PendingLogsAlertNotification =
    | {
          type: typeof LOGS_ALERT_NOTIFICATION_TYPE_SLACK
          slackWorkspaceId: number
          slackChannelId: string
          slackChannelName?: string
      }
    | {
          type: typeof LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK
          webhookUrl: string
      }

export const buildLogsAlertFilterConfig = (alertId: string): CyclotronJobFiltersType => ({
    properties: [
        {
            key: 'alert_id',
            value: alertId,
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ],
    events: [
        {
            id: LOGS_ALERT_FIRING_EVENT_ID,
            type: 'events',
        },
    ],
})

const LOGS_ALERT_SLACK_INPUTS =
    HOG_FUNCTION_SUB_TEMPLATES[LOGS_ALERT_FIRING_SUB_TEMPLATE_ID].find((t) => t.template_id === 'template-slack')
        ?.inputs ?? {}

export function buildLogsAlertHogFunctionPayload(
    alertId: string,
    alertName: string | undefined,
    notification: PendingLogsAlertNotification
): Partial<HogFunctionType> {
    const commonProps = HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES[LOGS_ALERT_FIRING_SUB_TEMPLATE_ID]
    const base = {
        type: commonProps.type,
        enabled: true,
        masking: null,
        filters: buildLogsAlertFilterConfig(alertId),
    }

    if (notification.type === 'slack') {
        return {
            ...base,
            name: `${alertName ?? 'Alert'}: Slack #${notification.slackChannelName ?? 'channel'}`,
            template_id: 'template-slack',
            inputs: {
                ...LOGS_ALERT_SLACK_INPUTS,
                slack_workspace: { value: notification.slackWorkspaceId },
                channel: { value: notification.slackChannelId },
            },
        }
    }

    return {
        ...base,
        name: `${alertName ?? 'Alert'}: Webhook ${notification.webhookUrl}`,
        template_id: 'template-webhook',
        inputs: {
            url: { value: notification.webhookUrl },
            body: {
                value: {
                    alert_name: '{event.properties.alert_name}',
                    threshold_count: '{event.properties.threshold_count}',
                    window_minutes: '{event.properties.window_minutes}',
                    logs_url: '{project.url}/logs?{event.properties.logs_url_params}',
                },
            },
        },
    }
}
