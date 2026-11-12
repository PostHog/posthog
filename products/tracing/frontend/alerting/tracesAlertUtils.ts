import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

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
    BillingAlertConfigurationStateEnumApi as PlatformAlertStateApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'
import { configurationStatus } from 'products/alerts_platform/frontend/platformAlertFormat'

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

/** Whether any group in the tree, at any depth, holds a filter. The API may save several outer groups. */
function hasFilters(filterGroup: UniversalFiltersGroup): boolean {
    return filterGroup.values.some((value) => !isUniversalGroupFilterLike(value) || hasFilters(value))
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
export type TracesAlertFormErrors = Partial<
    Record<'name' | 'threshold' | 'groupBy' | 'datapointsToAlarm' | 'evaluationPeriods' | 'cooldownMinutes', string>
>

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
    return { ...errors, ...validateChecks(form) }
}

function isWholeNumberBetween(value: number, min: number, max: number): boolean {
    return Number.isInteger(value) && value >= min && value <= max
}

/** The advanced settings, held to the API's bounds so a bad value fails here rather than on save. */
function validateChecks(form: TracesAlertFormType): TracesAlertFormErrors {
    const errors: TracesAlertFormErrors = {}
    if (!isWholeNumberBetween(form.evaluationPeriods, 1, MAX_EVALUATION_PERIODS)) {
        errors.evaluationPeriods = `Enter a whole number of checks from 1 to ${MAX_EVALUATION_PERIODS}`
    } else if (!isWholeNumberBetween(form.datapointsToAlarm, 1, form.evaluationPeriods)) {
        errors.datapointsToAlarm = `Enter a whole number of matching checks from 1 to ${form.evaluationPeriods}`
    }
    if (!isWholeNumberBetween(form.cooldownMinutes, 0, Number.MAX_SAFE_INTEGER)) {
        errors.cooldownMinutes = 'Enter a whole number of minutes, 0 or more'
    }
    return errors
}

/** A cleared number input reports NaN, which would otherwise reach the payload as null. */
export function finiteOr(value: number | undefined, fallback: number): number {
    return value !== undefined && Number.isFinite(value) ? value : fallback
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
    // A saved grouping the form can only approximate, such as one by operation alone, is kept until the
    // person picks another option, because new keys clear the alert's current groups.
    if (saved && groupByFromKeys(saved) === form.groupBy) {
        return saved
    }
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

export function measureLabel(condition: TracesPlatformAlertConditionApi): string {
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

/** A value in the measure's unit: a count, a percentage for error rate, or milliseconds for latency. */
export function formatMeasured(condition: TracesPlatformAlertConditionApi, value: number): string {
    switch (condition.measure) {
        case MeasureEnumApi.ErrorRate:
            return `${round(value * 100)}%`
        case MeasureEnumApi.Latency:
            return `${round(value)} ms`
        default:
            return String(round(value))
    }
}

/** One line, such as "p95 latency above 500 ms over 5 minutes". */
export function describeTracesCondition(condition: TracesPlatformAlertConditionApi | undefined): string {
    if (!condition) {
        return 'Unknown condition'
    }
    return `${measureLabel(condition)} ${condition.threshold_operator} ${formatMeasured(condition, condition.threshold)} over ${
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
export const NEW_ALERT_DESTINATIONS = { sourceKind: 'traces' }

export const SNOOZE_DURATIONS = [
    { label: '30 minutes', minutes: 30 },
    { label: '1 hour', minutes: 60 },
    { label: '4 hours', minutes: 240 },
    { label: '24 hours', minutes: 1440 },
]

/** The state the status tag shows. A broken or erroring check is the alert's, not one group's, so it comes first. */
export function indicatorState(alert: PlatformAlertConfigurationApi): PlatformAlertStateApi {
    if (alert.check_status === 'broken' || alert.check_status === 'errored') {
        return alert.check_status
    }
    // A whole-alert snooze is kept on the configuration, not on its groups' states.
    if (alert.enabled && alert.snooze_until && new Date(alert.snooze_until) > new Date()) {
        return 'snoozed'
    }
    const status = configurationStatus(alert)
    return status === 'disabled' || status === 'not_checked' ? 'not_firing' : status
}

// The API refuses a snooze further out than this, so a picked date past it gets a clear message instead.
export const MAX_SNOOZE_DAYS = 30

/** Why a snooze until `snoozeUntil` would be refused, or null when it is within the API's bounds. */
export function snoozeUntilError(snoozeUntil: string, now: Date = new Date()): string | null {
    const until = new Date(snoozeUntil).getTime()
    if (!(until > now.getTime())) {
        return 'Pick a time in the future.'
    }
    return until > now.getTime() + MAX_SNOOZE_DAYS * 24 * 60 * 60 * 1000
        ? `An alert can be snoozed for up to ${MAX_SNOOZE_DAYS} days.`
        : null
}
