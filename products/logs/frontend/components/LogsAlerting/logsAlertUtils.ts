import { lemonToast } from '@posthog/lemon-ui'

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

import { logsAlertsDestinationsList } from 'products/logs/frontend/generated/api'
import { LogsAlertConfigurationApi, LogsAlertDestinationConfigApi } from 'products/logs/frontend/generated/api.schemas'

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

export type PreEnableCheckResult = { ok: true } | { blocked: true; reason: string }

export function runPreEnableChecks(filters: PreEnableFilters): PreEnableCheckResult {
    if (!hasAnyFilter(filters.severityLevels, filters.serviceNames, filters.filterGroup)) {
        return { blocked: true, reason: 'Add at least one filter to enable' }
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

export function dispatchPreEnableCheck(result: PreEnableCheckResult, onConfirm: () => void): void {
    if ('blocked' in result) {
        lemonToast.error(result.reason)
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

// Slack channels the integrations API returned, plus the workspace they belong to. A
// destination in another workspace must not be labelled from this list, because two
// workspaces can use the same channel id for different channels.
export type SlackChannelLookup = {
    workspaceId: number | undefined
    channels: SlackChannelType[]
}

// The API returns a Slack channel id, never the channel name — creating a destination puts
// the name in the HogFunction name and stores nothing else. Names come from integrations.
export function destinationLabel(destination: LogsAlertDestinationConfigApi, slack: SlackChannelLookup): string {
    if (destination.type === LOGS_ALERT_NOTIFICATION_TYPE_SLACK) {
        const channelName =
            destination.slack_workspace_id === slack.workspaceId
                ? slack.channels.find((channel) => channel.id === destination.slack_channel_id)?.name
                : undefined
        return channelName ? `Slack #${channelName}` : 'Slack'
    }
    if (destination.type === LOGS_ALERT_NOTIFICATION_TYPE_TEAMS) {
        return destination.webhook_url ? `Microsoft Teams ${destination.webhook_url}` : 'Microsoft Teams'
    }
    return destination.webhook_url ? `Webhook ${destination.webhook_url}` : 'Webhook'
}

const DESTINATIONS_PAGE_SIZE = 100

// Walks every page. Alerts rarely hold more than a page of destinations, but a truncated
// list would hide destinations and let the user add one that already exists.
export async function fetchLogsAlertDestinations(
    projectId: string,
    alertId: string
): Promise<LogsAlertDestinationConfigApi[]> {
    const destinations: LogsAlertDestinationConfigApi[] = []
    for (let offset = 0; ; offset += DESTINATIONS_PAGE_SIZE) {
        const page = await logsAlertsDestinationsList(projectId, alertId, { limit: DESTINATIONS_PAGE_SIZE, offset })
        destinations.push(...page.results)
        if (page.results.length === 0 || destinations.length >= page.count) {
            return destinations
        }
    }
}
