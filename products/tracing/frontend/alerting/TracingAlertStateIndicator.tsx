import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { LogsAlertConfigurationStateEnumApi as TracingAlertConfigurationStateEnumApi } from 'products/tracing/frontend/generated/api.schemas'

import { TRACING_ALERT_STATE_LABELS } from './tracingAlertUtils'

const STATE_TAG_TYPE: Record<TracingAlertConfigurationStateEnumApi, LemonTagType> = {
    [TracingAlertConfigurationStateEnumApi.NotFiring]: 'success',
    [TracingAlertConfigurationStateEnumApi.Firing]: 'danger',
    [TracingAlertConfigurationStateEnumApi.PendingResolve]: 'warning',
    [TracingAlertConfigurationStateEnumApi.Errored]: 'danger',
    [TracingAlertConfigurationStateEnumApi.Snoozed]: 'muted',
    [TracingAlertConfigurationStateEnumApi.Broken]: 'danger',
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
    const label = TRACING_ALERT_STATE_LABELS[state] ?? state
    const type = STATE_TAG_TYPE[state] ?? ('default' as LemonTagType)
    const tag = (
        <LemonTag type={type} data-attr={`tracing-alert-state-${state}`}>
            {label}
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
