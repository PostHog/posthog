import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { LogsAlertConfigurationStateEnumApi } from 'products/logs/frontend/generated/api.schemas'

const STATE_CONFIG: Record<LogsAlertConfigurationStateEnumApi, { label: string; type: LemonTagType }> = {
    [LogsAlertConfigurationStateEnumApi.NotFiring]: { label: 'OK', type: 'success' },
    [LogsAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.PendingResolve]: { label: 'Resolving', type: 'warning' },
    [LogsAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', type: 'danger' },
    [LogsAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
}

interface LogsAlertStateIndicatorProps {
    state: LogsAlertConfigurationStateEnumApi
    snoozeUntil?: string | null
}

export function LogsAlertStateIndicator({ state, snoozeUntil }: LogsAlertStateIndicatorProps): JSX.Element {
    const config = STATE_CONFIG[state] ?? { label: state, type: 'default' as LemonTagType }
    const tag = <LemonTag type={config.type}>{config.label}</LemonTag>

    if (state === LogsAlertConfigurationStateEnumApi.Snoozed && snoozeUntil) {
        return (
            <Tooltip
                title={
                    <>
                        Until <TZLabel time={snoozeUntil} timestampStyle="absolute" />
                    </>
                }
            >
                {tag}
            </Tooltip>
        )
    }

    return tag
}
