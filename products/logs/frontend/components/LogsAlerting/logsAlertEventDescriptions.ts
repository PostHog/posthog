import type { LemonTagType } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { truncate } from 'lib/utils/strings'

import {
    AlertEvaluationHistoryPoint,
    AlertEvaluationThreshold,
} from 'products/alerts/frontend/components/AlertEvaluationHistoryChart'
import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationThresholdOperatorEnumApi,
    LogsAlertEventApi,
    LogsAlertEventKindEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

export function getHistoryThresholds(alert: LogsAlertConfigurationApi): AlertEvaluationThreshold[] {
    const thresholdValue = alert.threshold_count ?? 100
    if (alert.threshold_operator === LogsAlertConfigurationThresholdOperatorEnumApi.Below) {
        return [{ direction: 'lower', value: thresholdValue, label: `Below (${thresholdValue})` }]
    }
    return [{ direction: 'upper', value: thresholdValue, label: `Above (${thresholdValue})` }]
}

export function getHistoryPoints(events: LogsAlertEventApi[]): AlertEvaluationHistoryPoint[] {
    return events
        .filter((event) => event.kind === LogsAlertEventKindEnumApi.Check && event.result_count !== null)
        .sort((left, right) => left.created_at.localeCompare(right.created_at))
        .map((event) => ({
            label: dayjs(event.created_at).format('MMM D, HH:mm'),
            value: event.result_count ?? 0,
            firedAtTime: event.state_after === 'firing',
        }))
}

export interface EventDescription {
    label: string
    type: LemonTagType
    detail: string | null
}

const CONTROL_PLANE_DESCRIPTIONS: Record<
    Exclude<LogsAlertEventKindEnumApi, typeof LogsAlertEventKindEnumApi.Check>,
    Pick<EventDescription, 'label' | 'type'>
> = {
    [LogsAlertEventKindEnumApi.Reset]: { label: 'Reset', type: 'primary' },
    [LogsAlertEventKindEnumApi.Enable]: { label: 'Enabled', type: 'success' },
    [LogsAlertEventKindEnumApi.Disable]: { label: 'Disabled', type: 'muted' },
    [LogsAlertEventKindEnumApi.Snooze]: { label: 'Snoozed', type: 'highlight' },
    [LogsAlertEventKindEnumApi.Unsnooze]: { label: 'Unsnoozed', type: 'highlight' },
    [LogsAlertEventKindEnumApi.ThresholdChange]: { label: 'Threshold changed', type: 'completion' },
    [LogsAlertEventKindEnumApi.BrokenConfig]: { label: 'Broken config', type: 'caution' },
    [LogsAlertEventKindEnumApi.Handback]: { label: 'State restored', type: 'default' },
}

export function describeEvent(event: LogsAlertEventApi): EventDescription {
    if (event.kind !== LogsAlertEventKindEnumApi.Check) {
        return { ...CONTROL_PLANE_DESCRIPTIONS[event.kind], detail: formatTransition(event) }
    }
    if (event.error_message && event.state_after === 'broken') {
        return { label: 'Auto-disabled', type: 'caution', detail: '5 consecutive errors' }
    }
    if (event.error_message) {
        return { label: 'Errored', type: 'warning', detail: truncate(event.error_message, 80) }
    }
    if (event.state_before !== 'firing' && event.state_after === 'firing') {
        return {
            label: 'Fired',
            type: 'danger',
            detail:
                event.result_count !== null ? `${event.result_count} logs · threshold breached` : 'threshold breached',
        }
    }
    if (event.state_before === 'firing' && event.state_after !== 'firing') {
        return {
            label: 'Resolved',
            type: 'success',
            detail: event.result_count !== null ? `${event.result_count} logs · back to normal` : 'back to normal',
        }
    }
    return {
        label: 'Check',
        type: 'default',
        detail: event.result_count !== null ? `${event.result_count} logs` : null,
    }
}

function formatTransition(event: LogsAlertEventApi): string | null {
    if (event.state_before === event.state_after) {
        return null
    }
    return `${event.state_before} → ${event.state_after}`
}
