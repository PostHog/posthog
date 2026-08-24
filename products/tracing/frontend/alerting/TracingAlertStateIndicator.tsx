import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { LogsAlertConfigurationStateEnumApi as TracingAlertConfigurationStateEnumApi } from 'products/tracing/frontend/generated/api.schemas'

const STATE_CONFIG: Record<TracingAlertConfigurationStateEnumApi, { label: string; type: LemonTagType }> = {
    [TracingAlertConfigurationStateEnumApi.NotFiring]: { label: 'OK', type: 'success' },
    [TracingAlertConfigurationStateEnumApi.Firing]: { label: 'Firing', type: 'danger' },
    [TracingAlertConfigurationStateEnumApi.PendingResolve]: { label: 'Resolving', type: 'warning' },
    [TracingAlertConfigurationStateEnumApi.Errored]: { label: 'Errored', type: 'danger' },
    [TracingAlertConfigurationStateEnumApi.Snoozed]: { label: 'Snoozed', type: 'muted' },
    [TracingAlertConfigurationStateEnumApi.Broken]: { label: 'Broken', type: 'danger' },
}

const STATES_WITH_ERROR_TOOLTIP = new Set<TracingAlertConfigurationStateEnumApi>([
    TracingAlertConfigurationStateEnumApi.Errored,
    TracingAlertConfigurationStateEnumApi.Broken,
])

export function TracingAlertStateIndicator({
    state,
    enabled = true,
    firstEnabledAt = null,
    lastErrorMessage,
    snoozeUntil,
}: {
    state: TracingAlertConfigurationStateEnumApi
    enabled?: boolean
    firstEnabledAt?: string | null
    lastErrorMessage?: string | null
    snoozeUntil?: string | null
}): JSX.Element {
    if (!enabled) {
        if (firstEnabledAt == null) {
            return (
                <LemonTag type="warning" data-attr="tracing-alert-state-draft">
                    Draft
                </LemonTag>
            )
        }
        return (
            <LemonTag type="muted" data-attr="tracing-alert-state-disabled">
                Disabled
            </LemonTag>
        )
    }
    const config = STATE_CONFIG[state] ?? { label: state, type: 'default' as LemonTagType }
    const tag = (
        <LemonTag type={config.type} data-attr={`tracing-alert-state-${state}`}>
            {config.label}
        </LemonTag>
    )
    if (lastErrorMessage && STATES_WITH_ERROR_TOOLTIP.has(state)) {
        return <Tooltip title={lastErrorMessage}>{tag}</Tooltip>
    }
    if (state === TracingAlertConfigurationStateEnumApi.Snoozed && snoozeUntil) {
        return (
            <Tooltip
                title={
                    <>
                        Until <TZLabel time={snoozeUntil} />
                    </>
                }
            >
                {tag}
            </Tooltip>
        )
    }
    return tag
}
