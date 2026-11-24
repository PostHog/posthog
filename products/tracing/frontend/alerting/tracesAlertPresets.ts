import { AggregatedSpanRow } from '~/queries/schema/schema-general'

import {
    MeasureEnumApi,
    TracesAlertThresholdOperatorApi,
    WindowMinutesEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

import { OperationRoute, operationFilterGroup } from '../operationFilters'
import { TracesAlertFormType, emptyFilterGroup } from './tracesAlertUtils'

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

/** What a preset alert watches, and the current numbers it sets its threshold from. */
export interface TracesAlertPresetTarget {
    serviceName: string
    /** The span name to watch. Null watches every span of the service. */
    operation: string | null
    /** What the name shows in place of the span name, when the row is labelled differently. */
    label?: string
    /** The route attribute that narrows a bare-method span name to one endpoint. */
    route?: OperationRoute | null
    requestCount: number
    errorCount: number
    p95Ms: number | null
}

function presetCondition(
    target: TracesAlertPresetTarget,
    preset: TracesAlertPreset
): Pick<TracesAlertFormType, 'measure' | 'thresholdOperator' | 'threshold'> & { label: string } {
    switch (preset) {
        case 'error_rate': {
            const currentPercent = target.requestCount > 0 ? (target.errorCount / target.requestCount) * 100 : 0
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
                threshold: Math.max(1, Math.ceil((target.p95Ms ?? 0) * HEADROOM)),
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

/** Shortens the scope part of a long name, so the name fits the API and keeps what it alerts on. */
function presetName(target: TracesAlertPresetTarget, label: string): string {
    const shown = target.label ?? target.operation
    const scope = shown ? `${target.serviceName} ${shown}` : target.serviceName
    const suffix = `: ${label}`
    const room = MAX_NAME_LENGTH - suffix.length
    if (scope.length <= room) {
        return `${scope}${suffix}`
    }
    // Cut whole code points, since half an emoji is an unpaired surrogate the API rejects.
    let shortened = ''
    for (const char of scope) {
        if (shortened.length + char.length > room - 1) {
            break
        }
        shortened += char
    }
    return `${shortened}…${suffix}`
}

export function buildTargetPresetForm(target: TracesAlertPresetTarget, preset: TracesAlertPreset): TracesAlertFormType {
    const { label, ...condition } = presetCondition(target, preset)
    return {
        name: presetName(target, label),
        serviceNames: [target.serviceName],
        filterGroup:
            target.operation === null
                ? emptyFilterGroup()
                : operationFilterGroup(target.operation, null, target.route ?? null),
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

export function buildPresetForm(row: AggregatedSpanRow, preset: TracesAlertPreset): TracesAlertFormType {
    return buildTargetPresetForm(
        {
            serviceName: row.service_name,
            operation: row.name,
            requestCount: row.count,
            errorCount: row.error_count,
            p95Ms: row.p95_duration_nano / NANOS_PER_MILLISECOND,
        },
        preset
    )
}
