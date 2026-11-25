import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { LogsAlertConfigurationStateEnumApi } from 'products/logs/frontend/generated/api.schemas'

type BadgeVariant = 'default' | 'destructive' | 'warning' | 'success'

const STATE_CONFIG: Record<LogsAlertConfigurationStateEnumApi, { label: string; variant: BadgeVariant }> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: { label: 'OK', variant: 'success' },
    [LogsAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', variant: 'destructive' },
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: { label: 'Resolving', variant: 'warning' },
    [LogsAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', variant: 'destructive' },
    [LogsAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', variant: 'default' },
    [LogsAlertConfigurationStateEnumApi.Broken]: { label: 'Broken', variant: 'destructive' },
}

const STATES_WITH_ERROR_TOOLTIP = new Set<LogsAlertConfigurationStateEnumApi>([
    LogsAlertConfigurationStateEnumApi.Errored,
    LogsAlertConfigurationStateEnumApi.Broken,
])

export function QuillLogsAlertStateIndicator({
    state,
    enabled = true,
    firstEnabledAt = null,
    lastErrorMessage,
    snoozeUntil,
}: {
    state: LogsAlertConfigurationStateEnumApi
    enabled?: boolean
    firstEnabledAt?: string | null
    lastErrorMessage?: string | null
    snoozeUntil?: string | null
}): JSX.Element {
    if (!enabled) {
        if (firstEnabledAt == null) {
            return (
                <Badge variant="warning" data-attr="logs-alert-state-draft">
                    Draft
                </Badge>
            )
        }

        return <Badge data-attr="logs-alert-state-disabled">Disabled</Badge>
    }

    const config = STATE_CONFIG[state] ?? { label: state, variant: 'default' as BadgeVariant }
    const badge = (
        <Badge variant={config.variant} data-attr={`logs-alert-state-${state}`}>
            {config.label}
        </Badge>
    )

    if (lastErrorMessage && STATES_WITH_ERROR_TOOLTIP.has(state)) {
        return (
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>{badge}</TooltipTrigger>
                <TooltipContent className="max-w-80">{lastErrorMessage}</TooltipContent>
            </Tooltip>
        )
    }

    if (state === LogsAlertConfigurationStateEnumApi.Snoozed && snoozeUntil) {
        return (
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" />}>{badge}</TooltipTrigger>
                <TooltipContent>
                    <span>
                        Until <TZLabel time={snoozeUntil} />
                    </span>
                </TooltipContent>
            </Tooltip>
        )
    }

    return badge
}
