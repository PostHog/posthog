import {
    GroupingApi,
    GroupingModeEnumApi,
    MetricsPlatformAlertConditionApi,
    MetricsPlatformAlertConditionApiOperator,
    MetricsPlatformAlertConditionKindEnumApi,
    MetricsPlatformAlertConfigApi,
    MetricsPlatformAlertConfigurationEditApi,
    PlatformAlertConfigurationApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export type MetricsAlertOperator = NonNullable<MetricsPlatformAlertConditionApiOperator>

export interface MetricsAlertFormType {
    name: string
    query: string
    conditionKind: MetricsPlatformAlertConditionKindEnumApi
    operator: MetricsAlertOperator
    threshold: number | null
    groupByLabels: string[]
    evaluationPeriods: number
    datapointsToAlarm: number
    cooldownMinutes: number
}

export const OPERATOR_SYMBOLS: Record<MetricsAlertOperator, string> = {
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    eq: '=',
    ne: '≠',
}

export const OPERATOR_OPTIONS: { value: MetricsAlertOperator; label: string }[] = [
    { value: 'gt', label: 'Above' },
    { value: 'gte', label: 'At or above' },
    { value: 'lt', label: 'Below' },
    { value: 'lte', label: 'At or below' },
    { value: 'eq', label: 'Equal to' },
    { value: 'ne', label: 'Not equal to' },
]

export function metricsSourceConfig(alert: PlatformAlertConfigurationApi): MetricsPlatformAlertConfigApi | null {
    const { query, condition } = alert.source_config as Partial<MetricsPlatformAlertConfigApi>
    if (typeof query !== 'string' || typeof condition !== 'object' || condition === null) {
        return null
    }
    return { query, condition }
}

const NEW_ALERT_FORM: MetricsAlertFormType = {
    name: '',
    query: '',
    conditionKind: MetricsPlatformAlertConditionKindEnumApi.Threshold,
    operator: 'gt',
    threshold: null,
    groupByLabels: [],
    evaluationPeriods: 1,
    datapointsToAlarm: 1,
    cooldownMinutes: 0,
}

function conditionFields(
    condition: MetricsPlatformAlertConditionApi | undefined
): Pick<MetricsAlertFormType, 'conditionKind' | 'operator' | 'threshold'> {
    return {
        conditionKind: condition?.kind ?? NEW_ALERT_FORM.conditionKind,
        operator: condition?.operator ?? NEW_ALERT_FORM.operator,
        threshold: condition?.threshold ?? null,
    }
}

export function buildFormDefaults(alert: PlatformAlertConfigurationApi | null): MetricsAlertFormType {
    if (!alert) {
        return NEW_ALERT_FORM
    }
    const config = metricsSourceConfig(alert)
    return {
        name: alert.name,
        query: config?.query ?? '',
        ...conditionFields(config?.condition),
        groupByLabels: alert.grouping.mode === GroupingModeEnumApi.ByResultLabels ? (alert.grouping.keys ?? []) : [],
        evaluationPeriods: alert.evaluation_periods,
        datapointsToAlarm: alert.datapoints_to_alarm,
        cooldownMinutes: alert.cooldown_minutes,
    }
}

export interface MetricsAlertFormErrors {
    name?: string
    query?: string
    threshold?: string
    datapointsToAlarm?: string
}

export function validateForm(form: MetricsAlertFormType): MetricsAlertFormErrors {
    return {
        name: form.name.trim() ? undefined : 'Enter an alert name.',
        query: form.query.trim() ? undefined : 'Enter a PromQL query.',
        threshold:
            form.conditionKind === MetricsPlatformAlertConditionKindEnumApi.Threshold && form.threshold === null
                ? 'Enter a threshold.'
                : undefined,
        datapointsToAlarm:
            form.datapointsToAlarm > form.evaluationPeriods
                ? 'Cannot be more than the number of checks considered.'
                : undefined,
    }
}

// The API refuses a present condition that carries an operator or a threshold.
function toCondition(form: MetricsAlertFormType): MetricsPlatformAlertConditionApi {
    if (form.conditionKind === MetricsPlatformAlertConditionKindEnumApi.Present) {
        return { kind: MetricsPlatformAlertConditionKindEnumApi.Present }
    }
    return {
        kind: MetricsPlatformAlertConditionKindEnumApi.Threshold,
        operator: form.operator,
        threshold: form.threshold,
    }
}

function toGrouping(form: MetricsAlertFormType): GroupingApi {
    return form.groupByLabels.length > 0
        ? { mode: GroupingModeEnumApi.ByResultLabels, keys: form.groupByLabels }
        : { mode: GroupingModeEnumApi.Single }
}

export type MetricsAlertWritePayload = Pick<
    MetricsPlatformAlertConfigurationEditApi,
    'name' | 'source_config' | 'grouping' | 'evaluation_periods' | 'datapoints_to_alarm' | 'cooldown_minutes'
>

export function toWritePayload(form: MetricsAlertFormType): MetricsAlertWritePayload {
    return {
        name: form.name.trim(),
        source_config: { query: form.query.trim(), condition: toCondition(form) },
        grouping: toGrouping(form),
        evaluation_periods: form.evaluationPeriods,
        datapoints_to_alarm: form.datapointsToAlarm,
        cooldown_minutes: form.cooldownMinutes,
    }
}

export function describeMetricsCondition(condition: MetricsPlatformAlertConditionApi | undefined): string {
    if (!condition) {
        return 'Unknown condition'
    }
    if (condition.kind === MetricsPlatformAlertConditionKindEnumApi.Present) {
        return 'Any series returned'
    }
    if (!condition.operator || condition.threshold === null || condition.threshold === undefined) {
        return 'Unknown condition'
    }
    return `Value ${OPERATOR_SYMBOLS[condition.operator]} ${condition.threshold}`
}
