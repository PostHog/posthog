import {
    MetricsPlatformAlertConditionApi,
    MetricsPlatformAlertConditionApiOperator,
    MetricsPlatformAlertConditionKindEnumApi,
    MetricsPlatformAlertConfigApi,
    PlatformAlertConfigurationApi,
} from 'products/alerts_platform/frontend/generated/api.schemas'

export type MetricsAlertOperator = NonNullable<MetricsPlatformAlertConditionApiOperator>

export const OPERATOR_SYMBOLS: Record<MetricsAlertOperator, string> = {
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    eq: '=',
    ne: '≠',
}

export function metricsSourceConfig(alert: PlatformAlertConfigurationApi): MetricsPlatformAlertConfigApi | null {
    const { query, condition } = alert.source_config as Partial<MetricsPlatformAlertConfigApi>
    if (typeof query !== 'string' || typeof condition !== 'object' || condition === null) {
        return null
    }
    return { query, condition }
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
