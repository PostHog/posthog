import { AggregatedSpanRow } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    MeasureEnumApi,
    TracesAlertThresholdOperatorApi,
    WindowMinutesEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { TracesAlertFormType } from './tracesAlertUtils'

export type TracesAlertPreset = 'error_rate' | 'p95_latency' | 'requests_stopped'

export const TRACES_ALERT_PRESETS: { value: TracesAlertPreset; label: string }[] = [
    { value: 'error_rate', label: 'Error rate is high' },
    { value: 'p95_latency', label: 'p95 latency is high' },
    { value: 'requests_stopped', label: 'Requests stop' },
]

// A new alert fires at half again the current value, so normal noise does not fire it.
const HEADROOM = 1.5
const MIN_ERROR_RATE_PERCENT = 1
// The check fires strictly above the threshold, so a 100% threshold could never fire.
const MAX_ERROR_RATE_PERCENT = 99
// The API's limit on an alert name.
const MAX_NAME_LENGTH = 255
const NANOS_PER_MILLISECOND = 1_000_000

function operationFilterGroup(spanName: string): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: PropertyFilterType.Span,
                        key: 'name',
                        operator: PropertyOperator.Exact,
                        value: [spanName],
                    },
                ],
            },
        ],
    }
}

function presetCondition(
    row: AggregatedSpanRow,
    preset: TracesAlertPreset
): Pick<TracesAlertFormType, 'measure' | 'thresholdOperator' | 'threshold'> & { label: string } {
    switch (preset) {
        case 'error_rate': {
            const currentPercent = row.count > 0 ? (row.error_count / row.count) * 100 : 0
            const threshold = Math.min(
                MAX_ERROR_RATE_PERCENT,
                Math.max(MIN_ERROR_RATE_PERCENT, currentPercent * HEADROOM)
            )
            return {
                label: 'error rate',
                measure: MeasureEnumApi.ErrorRate,
                thresholdOperator: TracesAlertThresholdOperatorApi.Above,
                threshold: Math.round(threshold * 10) / 10,
            }
        }
        case 'p95_latency':
            return {
                label: 'p95 latency',
                measure: MeasureEnumApi.Latency,
                thresholdOperator: TracesAlertThresholdOperatorApi.Above,
                threshold: Math.max(1, Math.ceil((row.p95_duration_nano / NANOS_PER_MILLISECOND) * HEADROOM)),
            }
        case 'requests_stopped':
            // Below 1 fires on a window with no requests at all.
            return {
                label: 'no requests',
                measure: MeasureEnumApi.RequestCount,
                thresholdOperator: TracesAlertThresholdOperatorApi.Below,
                threshold: 1,
            }
    }
}

/** Why a row cannot take an alert preset: the alert check counts entry spans only. */
export function presetDisabledReason(row: AggregatedSpanRow): string | undefined {
    // Results cached before the count existed leave it out, so only a known zero disables the presets.
    return row.entry_span_count === 0 ? 'Alerts check entry spans (server, consumer or root) only' : undefined
}

/** Shortens the operation part of a long name, so the name fits the API and keeps what it alerts on. */
function presetName(row: AggregatedSpanRow, label: string): string {
    const operation = `${row.service_name} ${row.name}`
    const suffix = `: ${label}`
    const room = MAX_NAME_LENGTH - suffix.length
    return `${operation.length > room ? `${operation.slice(0, room - 1)}…` : operation}${suffix}`
}

export function buildPresetForm(row: AggregatedSpanRow, preset: TracesAlertPreset): TracesAlertFormType {
    const { label, ...condition } = presetCondition(row, preset)
    return {
        name: presetName(row, label),
        serviceNames: [row.service_name],
        filterGroup: operationFilterGroup(row.name),
        ...condition,
        percentile: 95,
        windowMinutes: WindowMinutesEnumApi.Number5,
        // Ungrouped, because a grouped alert cannot fire below a threshold.
        groupBy: 'none',
        evaluationPeriods: 1,
        datapointsToAlarm: 1,
        cooldownMinutes: 0,
    }
}
