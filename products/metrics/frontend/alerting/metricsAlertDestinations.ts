import {
    ALERT_PAGERDUTY_REGION_OPTIONS,
    ALERT_PAGERDUTY_SEVERITY_OPTIONS,
    AlertNotificationUrlInput,
    AlertPagerDutyRegion,
    AlertPagerDutySeverity,
    pagerDutyPendingDetail,
} from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import {
    PlatformAlertCreateDestinationApi,
    PlatformAlertDestinationApi,
    PlatformAlertDestinationTypeEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export const DESTINATION_TYPE_OPTIONS: { label: string; value: PlatformAlertDestinationTypeEnumApi }[] = [
    { label: 'Slack', value: PlatformAlertDestinationTypeEnumApi.Slack },
    { label: 'Microsoft Teams', value: PlatformAlertDestinationTypeEnumApi.Teams },
    { label: 'Discord', value: PlatformAlertDestinationTypeEnumApi.Discord },
    { label: 'PagerDuty', value: PlatformAlertDestinationTypeEnumApi.Pagerduty },
    { label: 'Webhook', value: PlatformAlertDestinationTypeEnumApi.Webhook },
]

const TYPE_LABELS = Object.fromEntries(DESTINATION_TYPE_OPTIONS.map(({ value, label }) => [value, label])) as Record<
    PlatformAlertDestinationTypeEnumApi,
    string
>

const URL_INPUTS: Partial<Record<PlatformAlertDestinationTypeEnumApi, AlertNotificationUrlInput>> = {
    [PlatformAlertDestinationTypeEnumApi.Teams]: {
        placeholder: 'https://prod-00.westus.logic.azure.com:443/workflows/...',
        helpText: 'Paste the URL from a Teams "Workflows" (Power Automate) or incoming webhook connector.',
    },
    [PlatformAlertDestinationTypeEnumApi.Discord]: {
        placeholder: 'https://discord.com/api/webhooks/...',
        helpText: 'Paste the webhook URL from the Discord channel settings, under Integrations.',
    },
    [PlatformAlertDestinationTypeEnumApi.Webhook]: { placeholder: 'https://example.com/webhook' },
}

export function urlInputFor(type: PlatformAlertDestinationTypeEnumApi): AlertNotificationUrlInput | undefined {
    return URL_INPUTS[type]
}

function pagerDutyDetail(severity?: string, region?: string): string {
    const severityLabel = ALERT_PAGERDUTY_SEVERITY_OPTIONS.find((option) => option.value === severity)?.label
    const regionLabel = ALERT_PAGERDUTY_REGION_OPTIONS.find((option) => option.value === region)?.label
    return [severityLabel ?? severity, regionLabel ?? region].filter(Boolean).join(' · ')
}

export interface DestinationDescription {
    title: string
    detail?: string
}

export function describeDestination(destination: PlatformAlertDestinationApi): DestinationDescription {
    const title = TYPE_LABELS[destination.type] ?? destination.type
    switch (destination.type) {
        case PlatformAlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name || destination.slack_channel_id || 'channel'}` }
        case PlatformAlertDestinationTypeEnumApi.Pagerduty:
            return {
                title,
                // The API returns only the key's last four characters.
                detail: [
                    `••••${destination.pagerduty_routing_key ?? ''}`,
                    pagerDutyDetail(destination.pagerduty_severity, destination.pagerduty_region),
                ].join(' · '),
            }
        default:
            return { title, detail: destination.webhook_url }
    }
}

export function describePendingDestination(destination: PlatformAlertCreateDestinationApi): DestinationDescription {
    const title = TYPE_LABELS[destination.type] ?? destination.type
    switch (destination.type) {
        case PlatformAlertDestinationTypeEnumApi.Slack:
            return { title, detail: `#${destination.slack_channel_name ?? destination.slack_channel_id ?? 'channel'}` }
        case PlatformAlertDestinationTypeEnumApi.Pagerduty:
            return {
                title,
                detail: pagerDutyPendingDetail({
                    routingKey: destination.pagerduty_routing_key ?? '',
                    severity: (destination.pagerduty_severity ?? 'critical') as AlertPagerDutySeverity,
                    region: (destination.pagerduty_region ?? 'us') as AlertPagerDutyRegion,
                }),
            }
        default:
            return { title, detail: destination.webhook_url }
    }
}
