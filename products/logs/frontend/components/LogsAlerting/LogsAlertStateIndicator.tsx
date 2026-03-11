import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { LogsAlertConfigurationStateEnumApi } from 'products/logs/frontend/generated/api.schemas'

const STATE_CONFIG: Record<LogsAlertConfigurationStateEnumApi, { label: string; type: LemonTagType }> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: { label: 'OK', type: 'success' },
    [LogsAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: { label: 'Resolving', type: 'warning' },
    [LogsAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
}

export function LogsAlertStateIndicator({ state }: { state: LogsAlertConfigurationStateEnumApi }): JSX.Element {
    const config = STATE_CONFIG[state] ?? { label: state, type: 'default' as LemonTagType }
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
