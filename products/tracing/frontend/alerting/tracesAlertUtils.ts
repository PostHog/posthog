import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import {
    GroupingApi,
    GroupingModeEnumApi,
    MeasureEnumApi,
    PlatformAlertConfigurationApi,
    PropertyGroupFilterApi,
    TracesAlertThresholdOperatorApi,
    TracesPlatformAlertConditionApi,
    TracesPlatformAlertConfigApi,
    WindowMinutesEnumApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export type TracesAlertPercentile = 50 | 90 | 95 | 99

/** How a grouped alert splits requests. Operation names are unbounded, so they only ever come with a service. */
export type TracesAlertGroupBy = 'none' | 'service' | 'service_and_operation'

export interface TracesAlertFormType {
    name: string
    serviceNames: string[]
    filterGroup: UniversalFiltersGroup
    measure: MeasureEnumApi
    percentile: TracesAlertPercentile
    thresholdOperator: TracesAlertThresholdOperatorApi
    /** In the unit the form shows: a count, a percentage for error rate, or milliseconds. */
    threshold: number | null
    windowMinutes: WindowMinutesEnumApi
    groupBy: TracesAlertGroupBy
    evaluationPeriods: number
    datapointsToAlarm: number
    cooldownMinutes: number
}

export const MAX_EVALUATION_PERIODS = 10

export const MEASURE_OPTIONS: { value: MeasureEnumApi; label: string }[] = [
    { value: MeasureEnumApi.RequestCount, label: 'Request count' },
    { value: MeasureEnumApi.ErrorCount, label: 'Error count' },
    { value: MeasureEnumApi.ErrorRate, label: 'Error rate' },
    { value: MeasureEnumApi.Latency, label: 'Latency' },
]

export const PERCENTILE_OPTIONS: { value: TracesAlertPercentile; label: string }[] = [
    { value: 50, label: 'p50' },
    { value: 90, label: 'p90' },
    { value: 95, label: 'p95' },
    { value: 99, label: 'p99' },
]

export const OPERATOR_OPTIONS: { value: TracesAlertThresholdOperatorApi; label: string }[] = [
    { value: TracesAlertThresholdOperatorApi.Above, label: 'above' },
    { value: TracesAlertThresholdOperatorApi.Below, label: 'below' },
]

export const WINDOW_OPTIONS: { value: WindowMinutesEnumApi; label: string }[] = [
    { value: WindowMinutesEnumApi.Number5, label: '5 minutes' },
    { value: WindowMinutesEnumApi.Number10, label: '10 minutes' },
    { value: WindowMinutesEnumApi.Number15, label: '15 minutes' },
    { value: WindowMinutesEnumApi.Number30, label: '30 minutes' },
    { value: WindowMinutesEnumApi.Number60, label: '60 minutes' },
]

// The keys are the trace_spans columns the platform groups on, so they must match the backend's GROUP_COLUMNS.
const GROUPING_KEYS: Record<TracesAlertGroupBy, string[]> = {
    none: [],
    service: ['service_name'],
    service_and_operation: ['service_name', 'name'],
}

export const GROUP_BY_OPTIONS: { value: TracesAlertGroupBy; label: string }[] = [
    { value: 'none', label: 'All matching requests together' },
    { value: 'service', label: 'Each service' },
    { value: 'service_and_operation', label: 'Each service and operation' },
]

const MEASURE_UNITS: Record<MeasureEnumApi, string> = {
    [MeasureEnumApi.RequestCount]: 'requests',
    [MeasureEnumApi.ErrorCount]: 'errors',
    [MeasureEnumApi.ErrorRate]: '%',
    [MeasureEnumApi.Latency]: 'ms',
}

export function thresholdUnit(measure: MeasureEnumApi): string {
    return MEASURE_UNITS[measure]
}

export function emptyFilterGroup(): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: [] }],
    }
}

function hasFilters(filterGroup: UniversalFiltersGroup): boolean {
    const inner = filterGroup.values[0] as UniversalFiltersGroup | undefined
    return (inner?.values.length ?? 0) > 0
}

export function tracesSourceConfig(alert: PlatformAlertConfigurationApi): TracesPlatformAlertConfigApi | null {
    const config = alert.source_config as Partial<TracesPlatformAlertConfigApi>
    return config.condition ? (config as TracesPlatformAlertConfigApi) : null
}

function groupByFromKeys(grouping: GroupingApi | undefined): TracesAlertGroupBy {
    if (grouping?.mode !== GroupingModeEnumApi.ByResultLabels) {
        return 'none'
    }
    return grouping.keys?.includes('name') ? 'service_and_operation' : 'service'
}

/** A saved threshold in the unit the form shows, which is a percentage for error rate. */
function formThreshold(condition: TracesPlatformAlertConditionApi): number {
    return condition.measure === MeasureEnumApi.ErrorRate ? round(condition.threshold * 100) : condition.threshold
}

/** The form's starting values: the saved alert when editing, otherwise the viewer's current filters. */
export function buildFormDefaults(
    alert: PlatformAlertConfigurationApi | null,
    viewerFilters?: { serviceNames: string[]; filterGroup: UniversalFiltersGroup }
): TracesAlertFormType {
    const config = alert ? tracesSourceConfig(alert) : null
    const condition = config?.condition
    const measure = condition?.measure ?? MeasureEnumApi.ErrorRate
    return {
        name: alert?.name ?? '',
        serviceNames: config?.filters?.serviceNames ?? viewerFilters?.serviceNames ?? [],
        filterGroup:
            (config?.filters?.filterGroup as unknown as UniversalFiltersGroup | null | undefined) ??
            viewerFilters?.filterGroup ??
            emptyFilterGroup(),
        measure,
        percentile: (condition?.percentile ?? 95) as TracesAlertPercentile,
        thresholdOperator: condition?.threshold_operator ?? TracesAlertThresholdOperatorApi.Above,
        threshold: condition ? formThreshold(condition) : null,
        windowMinutes: condition?.window_minutes ?? WindowMinutesEnumApi.Number5,
        groupBy: groupByFromKeys(alert?.grouping),
        evaluationPeriods: alert?.evaluation_periods ?? 1,
        datapointsToAlarm: alert?.datapoints_to_alarm ?? 1,
        cooldownMinutes: alert?.cooldown_minutes ?? 0,
    }
}

// Percent to fraction and back loses float precision (7% reads back as 7.000000000000001).
function round(value: number): number {
    return Math.round(value * 1e6) / 1e6
}

/** Only the fields that can be wrong, so the type fits kea-forms' per-field error map. */
export type TracesAlertFormErrors = Partial<Record<'name' | 'threshold' | 'groupBy' | 'datapointsToAlarm', string>>

/** kea-forms types an error as any of string, boolean or null; the fields here only ever hold a message. */
export function errorText(error: unknown): string | undefined {
    return typeof error === 'string' ? error : undefined
}

export function validateForm(form: TracesAlertFormType): TracesAlertFormErrors {
    const errors: TracesAlertFormErrors = {}
    if (!form.name.trim()) {
        errors.name = 'Enter a name'
    }
    if (form.threshold === null || Number.isNaN(form.threshold)) {
        errors.threshold = 'Enter a threshold'
    } else if (form.threshold < 0) {
        errors.threshold = 'The threshold cannot be negative'
    } else if (form.measure === MeasureEnumApi.ErrorRate && form.threshold > 100) {
        errors.threshold = 'An error rate is at most 100%'
    }
    if (form.groupBy !== 'none' && form.thresholdOperator === TracesAlertThresholdOperatorApi.Below) {
        errors.groupBy =
            'A grouped alert can only fire above a threshold. A group with no requests has nothing to check.'
    } else if (form.groupBy === 'service_and_operation' && form.serviceNames.length === 0) {
        errors.groupBy = 'Pick at least one service to group by operation'
    }
    if (form.datapointsToAlarm > form.evaluationPeriods) {
        errors.datapointsToAlarm = 'Cannot need more matching checks than checks considered'
    }
    return errors
}

export function toCondition(form: TracesAlertFormType): TracesPlatformAlertConditionApi {
    const threshold = form.threshold ?? 0
    return {
        measure: form.measure,
        percentile: form.measure === MeasureEnumApi.Latency ? form.percentile : null,
        threshold: form.measure === MeasureEnumApi.ErrorRate ? round(threshold / 100) : threshold,
        threshold_operator: form.thresholdOperator,
        window_minutes: form.windowMinutes,
    }
}

function toGrouping(form: TracesAlertFormType, saved: GroupingApi | undefined): GroupingApi {
    if (form.groupBy === 'none') {
        return { mode: GroupingModeEnumApi.Single, keys: [] }
    }
    // A grouping is replaced whole, so keep the saved group limit rather than reset it to the default.
    return {
        mode: GroupingModeEnumApi.ByResultLabels,
        keys: GROUPING_KEYS[form.groupBy],
        ...(saved?.max_instances !== undefined ? { max_instances: saved.max_instances } : {}),
    }
}

export interface TracesAlertWritePayload {
    name: string
    source_config: TracesPlatformAlertConfigApi
    grouping: GroupingApi
    evaluation_periods: number
    datapoints_to_alarm: number
    cooldown_minutes: number
}

export function toWritePayload(
    form: TracesAlertFormType,
    saved: PlatformAlertConfigurationApi | null = null
): TracesAlertWritePayload {
    return {
        name: form.name.trim(),
        source_config: {
            filters: {
                serviceNames: form.serviceNames,
                filterGroup: hasFilters(form.filterGroup)
                    ? (form.filterGroup as unknown as PropertyGroupFilterApi)
                    : null,
            },
            condition: toCondition(form),
        },
        grouping: toGrouping(form, saved?.grouping),
        evaluation_periods: form.evaluationPeriods,
        datapoints_to_alarm: form.datapointsToAlarm,
        cooldown_minutes: form.cooldownMinutes,
    }
}

function measureLabel(condition: TracesPlatformAlertConditionApi): string {
    switch (condition.measure) {
        case MeasureEnumApi.RequestCount:
            return 'Requests'
        case MeasureEnumApi.ErrorCount:
            return 'Errors'
        case MeasureEnumApi.ErrorRate:
            return 'Error rate'
        case MeasureEnumApi.Latency:
            return `p${condition.percentile} latency`
    }
}

function formatThreshold(condition: TracesPlatformAlertConditionApi): string {
    switch (condition.measure) {
        case MeasureEnumApi.ErrorRate:
            return `${round(condition.threshold * 100)}%`
        case MeasureEnumApi.Latency:
            return `${condition.threshold} ms`
        default:
            return String(condition.threshold)
    }
}

/** One line, such as "p95 latency above 500 ms over 5 minutes". */
export function describeTracesCondition(condition: TracesPlatformAlertConditionApi | undefined): string {
    if (!condition) {
        return 'Unknown condition'
    }
    return `${measureLabel(condition)} ${condition.threshold_operator} ${formatThreshold(condition)} over ${
        condition.window_minutes
    } minutes`
}

export function describeTracesScope(config: TracesPlatformAlertConfigApi | null): string {
    const services = config?.filters?.serviceNames ?? []
    const scope = services.length === 0 ? 'All services' : services.join(', ')
    const filterGroup = config?.filters?.filterGroup as unknown as UniversalFiltersGroup | null | undefined
    return filterGroup && hasFilters(filterGroup) ? `${scope}, with filters` : scope
}

/** Service and attribute suggestions come from the last day of spans, the range an alert's window falls in. */
export const SUGGESTION_RANGE = { date_from: '-24h' }

/** The destinations logic of an alert being created, whose destinations are added once it is saved. */
export const NEW_ALERT_DESTINATIONS = { alertId: null, sourceKind: 'traces' }

export function alertDestinations(alertId: string): { alertId: string; sourceKind: string } {
    return { alertId, sourceKind: 'traces' }
}
