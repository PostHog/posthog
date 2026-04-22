import { LemonDialog } from '@posthog/lemon-ui'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'
import { CyclotronJobFiltersType, HogFunctionType, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

export function withEnableNotificationGuard(
    alert: LogsAlertConfigurationApi,
    onConfirm: () => void,
    onConfigureNotifications: () => void
): void {
    const isEnabling = !(alert.enabled ?? true)
    if (isEnabling && (alert.destination_types ?? []).length === 0) {
        LemonDialog.open({
            title: 'No notifications configured',
            description:
                "This alert has no notification destinations. It will fire silently — you won't receive any alerts when conditions are met.",
            primaryButton: {
                children: 'Configure notifications',
                onClick: onConfigureNotifications,
            },
            secondaryButton: {
                children: 'Enable anyway',
                onClick: onConfirm,
            },
        })
        return
    }
    onConfirm()
}

export const SNOOZE_DURATIONS = [
    { label: '30 minutes', minutes: 30 },
    { label: '1 hour', minutes: 60 },
    { label: '4 hours', minutes: 240 },
    { label: '24 hours', minutes: 1440 },
]

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

// Filter used to list every HogFunction tied to a given alert, regardless of which
// event kind it handles. Deliberately omits the `events` array: the backend
// create endpoint fans out into one HogFunction per event kind, and JSONB `@>`
// matching would require a HogFunction's `filters.events` to contain every event
// we list — which no single HogFunction does post-fan-out. The `alert_id`
// property alone uniquely identifies all HogFunctions belonging to the alert.
export function hasAnyFilter(
    severityLevels: string[],
    serviceNames: string[],
    filterGroup: UniversalFiltersGroup
): boolean {
    return severityLevels.length > 0 || serviceNames.length > 0 || filterGroup.values.length > 0
}

export function buildAlertFilters(
    severityLevels: string[],
    serviceNames: string[],
    filterGroup: UniversalFiltersGroup
): Record<string, unknown> {
    const filters: Record<string, unknown> = {}
    if (severityLevels.length > 0) {
        filters.severityLevels = severityLevels
    }
    if (serviceNames.length > 0) {
        filters.serviceNames = serviceNames
    }
    if (filterGroup.values.length > 0) {
        filters.filterGroup = {
            type: FilterLogicalOperator.And,
            values: [filterGroup],
        }
    }
    return filters
}

export function buildLogsAlertFilterConfig(alertId: string): CyclotronJobFiltersType {
    return {
        properties: [
            {
                key: 'alert_id',
                value: alertId,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ],
    }
}

export type LogsAlertDestinationGroup = {
    key: string
    type: LogsAlertNotificationType
    label: string
    hogFunctions: HogFunctionType[]
    enabled: boolean
}

export function groupLogsAlertDestinations(
    hogFunctions: HogFunctionType[],
    resolveSlackLabel: (channelValue: string) => string | null
): LogsAlertDestinationGroup[] {
    const groups = new Map<string, LogsAlertDestinationGroup>()
    for (const hf of hogFunctions) {
        const slackChannelValue = hf.inputs?.channel?.value
        const webhookUrl = hf.inputs?.url?.value
        let key: string
        let type: LogsAlertNotificationType
        let label: string

        if (typeof slackChannelValue === 'string') {
            type = LOGS_ALERT_NOTIFICATION_TYPE_SLACK
            key = `slack:${slackChannelValue}`
            const channelName = resolveSlackLabel(slackChannelValue)
            label = channelName ? `Slack #${channelName}` : 'Slack'
        } else if (typeof webhookUrl === 'string') {
            type = LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK
            key = `webhook:${webhookUrl}`
            label = `Webhook ${webhookUrl}`
        } else {
            type = LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK
            key = `unknown:${hf.id}`
            label = hf.name
        }

        const existing = groups.get(key)
        if (existing) {
            existing.hogFunctions.push(hf)
            existing.enabled = existing.enabled && hf.enabled
        } else {
            groups.set(key, { key, type, label, hogFunctions: [hf], enabled: hf.enabled })
        }
    }
    return Array.from(groups.values())
}
