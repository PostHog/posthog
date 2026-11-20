import {
    LogsAlertConfigurationApi,
    LogsAlertConfigurationThresholdOperatorEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

export function formatThreshold(alert: LogsAlertConfigurationApi): string {
    const operator = alert.threshold_operator === LogsAlertConfigurationThresholdOperatorEnumApi.Below ? '<' : '>'
    return `${operator} ${alert.threshold_count} in ${alert.window_minutes}m`
}
