import {
    GroupingModeEnumApi,
    LogsAlertConfigurationApi,
    LogsAlertConfigurationStateEnumApi,
    LogsAlertGroupingApi,
} from 'products/logs/frontend/generated/api.schemas'

export type LogsAlertGroupBy = 'none' | 'service' | 'severity' | 'service_and_severity'

export const DEFAULT_GROUPED_MAX_INSTANCES = 20

export const GROUP_BY_LABELS: Record<LogsAlertGroupBy, string> = {
    none: "Don't group",
    service: 'Service',
    severity: 'Severity',
    service_and_severity: 'Service and severity',
}

export const GROUPING_NEEDS_ABOVE = 'Grouping only works when the alert fires above a threshold.'

export const SIMULATION_NEEDS_UNGROUPED =
    'Simulation can\'t show grouped alerts. Set Group by to "Don\'t group" to run one.'

export const MAX_INSTANCES_LIMIT = 100

const GROUP_BY_KEYS: Record<LogsAlertGroupBy, string[]> = {
    none: [],
    service: ['service_name'],
    severity: ['severity_text'],
    service_and_severity: ['service_name', 'severity_text'],
}

export function groupByOf(grouping: LogsAlertGroupingApi | undefined): LogsAlertGroupBy {
    if (!grouping || grouping.mode !== GroupingModeEnumApi.ByResultLabels) {
        return 'none'
    }
    const keys = new Set(grouping.keys ?? [])
    const match = (Object.keys(GROUP_BY_KEYS) as LogsAlertGroupBy[]).find(
        (groupBy) => GROUP_BY_KEYS[groupBy].length === keys.size && GROUP_BY_KEYS[groupBy].every((key) => keys.has(key))
    )
    return match ?? 'none'
}

/**
 * The grouping a save sends, or undefined to keep the stored one. The API compares keys in order, so
 * an unchanged selection sends the stored keys as they are. Otherwise a reordered or unrecognized
 * stored grouping would regroup the alert on an unrelated save.
 */
export function groupingPayloadOf(
    groupBy: LogsAlertGroupBy,
    maxInstances: number,
    stored: LogsAlertGroupingApi | undefined
): LogsAlertGroupingApi | undefined {
    const unchanged = stored !== undefined && groupByOf(stored) === groupBy
    if (groupBy === 'none') {
        return unchanged ? undefined : { mode: GroupingModeEnumApi.Single }
    }
    const keys = unchanged && stored.keys ? stored.keys : GROUP_BY_KEYS[groupBy]
    return { mode: GroupingModeEnumApi.ByResultLabels, keys, max_instances: maxInstances }
}

export function maxInstancesError(groupBy: LogsAlertGroupBy, maxInstances: number | undefined): string | undefined {
    if (groupBy === 'none') {
        return undefined
    }
    const valid =
        maxInstances !== undefined &&
        Number.isInteger(maxInstances) &&
        maxInstances >= 1 &&
        maxInstances <= MAX_INSTANCES_LIMIT
    return valid ? undefined : `Enter a whole number from 1 to ${MAX_INSTANCES_LIMIT}.`
}

export function isRegroup(alert: LogsAlertConfigurationApi | null, groupBy: LogsAlertGroupBy): boolean {
    return alert !== null && groupByOf(alert.grouping) !== groupBy
}

/**
 * Only an alert the alerts platform evaluates can group. A new alert goes to the platform once the
 * team has any logs alert there, which mirrors the backend's cutover check.
 */
export function canGroupAlert(
    alert: LogsAlertConfigurationApi | null,
    teamAlerts: LogsAlertConfigurationApi[]
): boolean {
    if (!alert) {
        return teamAlerts.some((candidate) => candidate.platform_owned)
    }
    return alert.platform_owned || alert.grouping?.mode === GroupingModeEnumApi.ByResultLabels
}

/** What a save that changes the grouping does to the state the alert tracks now. */
export function regroupConfirmationText(alert: LogsAlertConfigurationApi | null): string {
    if (alert?.grouping?.mode === GroupingModeEnumApi.ByResultLabels) {
        return "Saving resets every group this alert tracks. Groups that are firing now won't get a resolve message for their open notifications."
    }
    const reset = "Saving resets this alert's state, and it starts tracking each group on its own."
    const hasOpenNotification =
        alert?.state === LogsAlertConfigurationStateEnumApi.Firing ||
        alert?.state === LogsAlertConfigurationStateEnumApi.PendingResolve
    if (hasOpenNotification) {
        return `${reset} The alert is firing now, so its open notification won't get a resolve message.`
    }
    return reset
}
