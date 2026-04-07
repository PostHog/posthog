import {
    LOGS_ALERT_FIRING_EVENT_ID,
    LOGS_ALERT_FIRING_SUB_TEMPLATE_ID,
    LOGS_ALERT_RESOLVED_EVENT_ID,
} from 'lib/constants'
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
        {
            id: LOGS_ALERT_RESOLVED_EVENT_ID,
            type: 'events',
        },
    ],
})

const LOGS_ALERT_SLACK_BLOCKS = [
    {
        type: 'header',
        text: {
            type: 'plain_text',
            text: "Log alert '{event.properties.alert_name}' {if(event.event == '$logs_alert_resolved', 'has resolved', 'is firing')}",
        },
    },
    {
        type: 'section',
        text: {
            type: 'mrkdwn',
            text: "*{if(event.event == '$logs_alert_resolved', 'Current count', 'Threshold breached')}:* {event.properties.result_count} logs in {event.properties.window_minutes}m (threshold: {event.properties.threshold_operator} {event.properties.threshold_count})",
        },
    },
    {
        type: 'context',
        elements: [
            {
                type: 'mrkdwn',
                text: [
                    '{if(length(event.properties.severity_levels) > 0 or length(event.properties.service_names) > 0, concat(',
                    "if(length(event.properties.severity_levels) > 0, concat('Severity: ', arrayStringConcat(event.properties.severity_levels, ', ')), ''),",
                    "if(length(event.properties.severity_levels) > 0 and length(event.properties.service_names) > 0, ' | ', ''),",
                    "if(length(event.properties.service_names) > 0, concat('Services: ', arrayStringConcat(event.properties.service_names, ', ')), '')",
                    "), 'All log levels and services')}",
                ].join(''),
            },
            { type: 'mrkdwn', text: 'Project: <{project.url}|{project.name}>' },
        ],
    },
    { type: 'divider' },
    {
        type: 'actions',
        elements: [
            {
                url: '{project.url}/logs?{event.properties.logs_url_params}',
                text: { text: 'View logs', type: 'plain_text' },
                type: 'button',
            },
        ],
    },
]

const BASE_SLACK_INPUTS =
    HOG_FUNCTION_SUB_TEMPLATES[LOGS_ALERT_FIRING_SUB_TEMPLATE_ID].find((t) => t.template_id === 'template-slack')
        ?.inputs ?? {}

const LOGS_ALERT_SLACK_INPUTS = {
    ...BASE_SLACK_INPUTS,
    blocks: { value: LOGS_ALERT_SLACK_BLOCKS },
    text: {
        value: "Log alert '{event.properties.alert_name}' {if(event.event == '$logs_alert_resolved', 'has resolved', 'is firing')}",
    },
}

const LOGS_ALERT_WEBHOOK_BODY: Record<string, string> = {
    event: "{if(event.event == '$logs_alert_resolved', 'resolved', 'firing')}",
    alert_id: '{event.properties.alert_id}',
    alert_name: '{event.properties.alert_name}',
    result_count: '{event.properties.result_count}',
    threshold_count: '{event.properties.threshold_count}',
    threshold_operator: '{event.properties.threshold_operator}',
    window_minutes: '{event.properties.window_minutes}',
    service_names: '{event.properties.service_names}',
    severity_levels: '{event.properties.severity_levels}',
    logs_url: '{project.url}/logs?{event.properties.logs_url_params}',
    triggered_at: '{event.properties.triggered_at}',
}

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
            body: { value: LOGS_ALERT_WEBHOOK_BODY },
        },
    }
}
