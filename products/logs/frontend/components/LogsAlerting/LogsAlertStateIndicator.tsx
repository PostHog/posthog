import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { LogsAlertConfigurationStateEnumApi } from 'products/logs/frontend/generated/api.schemas'

const STATE_CONFIG: Record<LogsAlertConfigurationStateEnumApi, { label: string; type: LemonTagType }> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: { label: 'OK', type: 'success' },
    [LogsAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: { label: 'Resolving', type: 'warning' },
    [LogsAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
    [LogsAlertConfigurationStateEnumApi.Broken]: { label: 'Broken', type: 'danger' },
}

const STATES_WITH_ERROR_TOOLTIP = new Set<LogsAlertConfigurationStateEnumApi>([
    LogsAlertConfigurationStateEnumApi.Errored,
    LogsAlertConfigurationStateEnumApi.Broken,
])

export function LogsAlertStateIndicator({
    state,
    lastErrorMessage,
}: {
    state: LogsAlertConfigurationStateEnumApi
    lastErrorMessage?: string | null
}): JSX.Element {
    const config = STATE_CONFIG[state] ?? { label: state, type: 'default' as LemonTagType }
    const tag = <LemonTag type={config.type}>{config.label}</LemonTag>
    if (lastErrorMessage && STATES_WITH_ERROR_TOOLTIP.has(state)) {
        return <Tooltip title={lastErrorMessage}>{tag}</Tooltip>
    }
    return tag
}
