import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import {
    LOGS_ALERT_AUTO_DISABLED_EVENT_ID,
    LOGS_ALERT_ERRORED_EVENT_ID,
    LOGS_ALERT_FIRING_EVENT_ID,
    LOGS_ALERT_RESOLVED_EVENT_ID,
} from 'lib/constants'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'
import {
    CyclotronJobFiltersType,
    HogFunctionType,
    PropertyFilterType,
    PropertyOperator,
    SlackChannelType,
} from '~/types'

import { LogsAlertConfigurationApi } from 'products/logs/frontend/generated/api.schemas'

export type LogsAlertEventKind = 'firing' | 'resolved' | 'broken' | 'errored'

export const LOGS_ALERT_EVENT_KIND_ORDER: LogsAlertEventKind[] = ['firing', 'resolved', 'broken', 'errored']

export const LOGS_ALERT_EVENT_KIND_META: Record<LogsAlertEventKind, { label: string; description: string }> = {
    firing: {
        label: 'Firing',
        description: 'Sent when the alert starts firing.',
    },
    resolved: {
        label: 'Resolved',
        description: 'Sent when a firing alert returns to normal.',
    },
    broken: {
        label: 'Auto-disabled',
        description: 'Sent if the alert is auto-disabled after repeated check failures.',
    },
    errored: {
        label: 'Errored',
        description: "Sent when an alert check can't evaluate.",
    },
}

export function getHogFunctionEventKind(hf: HogFunctionType): LogsAlertEventKind | null {
    const eventId = hf.filters?.events?.[0]?.id
    switch (eventId) {
        case LOGS_ALERT_FIRING_EVENT_ID:
            return 'firing'
        case LOGS_ALERT_RESOLVED_EVENT_ID:
            return 'resolved'
        case LOGS_ALERT_AUTO_DISABLED_EVENT_ID:
            return 'broken'
        case LOGS_ALERT_ERRORED_EVENT_ID:
            return 'errored'
        default:
            return null
    }
}

export type PreEnableFilters = {
    severityLevels: string[]
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
}

export type PreEnableCheckResult =
    | { ok: true }
    | { blocked: true; reason: string }
    | {
          warning: {
              title: string
              description: string
              confirmLabel: string
          }
      }

export function runPreEnableChecks(alert: LogsAlertConfigurationApi, filters: PreEnableFilters): PreEnableCheckResult {
    if (!hasAnyFilter(filters.severityLevels, filters.serviceNames, filters.filterGroup)) {
        return { blocked: true, reason: 'Add at least one filter to enable' }
    }
    if ((alert.destination_types ?? []).length === 0) {
        return {
            warning: {
                title: 'No notifications configured',
                description:
                    "This alert has no notification destinations. It will fire silently — you won't receive any alerts when conditions are met.",
                confirmLabel: 'Enable anyway',
            },
        }
    }
    return { ok: true }
}

export function alertFiltersForPreEnableCheck(alert: LogsAlertConfigurationApi): PreEnableFilters {
    const filters = (alert.filters ?? {}) as Record<string, unknown>
    const filterGroupWrapper = filters.filterGroup as { values: UniversalFiltersGroup[] } | undefined
    return {
        severityLevels: (filters.severityLevels as string[] | undefined) ?? [],
        serviceNames: (filters.serviceNames as string[] | undefined) ?? [],
        filterGroup: filterGroupWrapper?.values?.[0] ?? { type: FilterLogicalOperator.And, values: [] },
    }
}

export function dispatchPreEnableCheck(
    result: PreEnableCheckResult,
    callbacks: { onConfirm: () => void; onConfigureNotifications: () => void }
): void {
    if ('blocked' in result) {
        lemonToast.error(result.reason)
        return
    }
    if ('warning' in result) {
        LemonDialog.open({
            title: result.warning.title,
            description: result.warning.description,
            primaryButton: {
                children: 'Configure notifications',
                onClick: callbacks.onConfigureNotifications,
                'data-attr': 'logs-alert-warning-configure-notifications',
            },
            secondaryButton: {
                children: result.warning.confirmLabel,
                onClick: callbacks.onConfirm,
                'data-attr': 'logs-alert-warning-enable-anyway',
            },
        })
        return
    }
    callbacks.onConfirm()
}

export const SNOOZE_DURATIONS = [
    { label: '30 minutes', minutes: 30 },
    { label: '1 hour', minutes: 60 },
    { label: '4 hours', minutes: 240 },
    { label: '24 hours', minutes: 1440 },
]

export const LOGS_ALERT_NOTIFICATION_TYPE_SLACK = 'slack' as const
export const LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK = 'webhook' as const
export const LOGS_ALERT_NOTIFICATION_TYPE_TEAMS = 'teams' as const
export type LogsAlertNotificationType =
    | typeof LOGS_ALERT_NOTIFICATION_TYPE_SLACK
    | typeof LOGS_ALERT_NOTIFICATION_TYPE_WEBHOOK
    | typeof LOGS_ALERT_NOTIFICATION_TYPE_TEAMS

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
    | {
          type: typeof LOGS_ALERT_NOTIFICATION_TYPE_TEAMS
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

export function slackChannelLabel(channelValue: string, slackChannels: SlackChannelType[]): string {
    const channelId = channelValue.split('|')[0]
    const name = slackChannels.find((c) => c.id === channelId)?.name
    return name ? `Slack #${name}` : 'Slack'
}

export function resolveGroupLabel(group: LogsAlertDestinationGroup, slackChannels: SlackChannelType[]): string {
    if (group.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK) {
        const hf = group.hogFunctions[0]
        const channelValue = hf?.inputs?.channel?.value
        if (typeof channelValue === 'string') {
            return slackChannelLabel(channelValue, slackChannels)
        }
    }
    return group.label
}

export function groupLogsAlertDestinations(
    hogFunctions: HogFunctionType[],
    resolveSlackLabel: (channelValue: string) => string | null
): LogsAlertDestinationGroup[] {
    const groups = new Map<string, LogsAlertDestinationGroup>()
    for (const hf of hogFunctions) {
        const slackChannelValue = hf.inputs?.channel?.value
        // The Microsoft Teams template stores its URL under `webhookUrl`; the generic webhook uses `url`.
        const teamsUrl = hf.inputs?.webhookUrl?.value
        const webhookUrl = hf.inputs?.url?.value
        let key: string
        let type: LogsAlertNotificationType
        let label: string

        if (typeof slackChannelValue === 'string') {
            type = LOGS_ALERT_NOTIFICATION_TYPE_SLACK
            key = `slack:${slackChannelValue}`
            const channelName = resolveSlackLabel(slackChannelValue)
            label = channelName ? `Slack #${channelName}` : 'Slack'
        } else if (typeof teamsUrl === 'string') {
            type = LOGS_ALERT_NOTIFICATION_TYPE_TEAMS
            key = `teams:${teamsUrl}`
            label = `Microsoft Teams ${teamsUrl}`
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
