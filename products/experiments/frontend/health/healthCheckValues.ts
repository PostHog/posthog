import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type {
    ExperimentExposureHealthCheckRule,
    ExperimentExposureQueryResponse,
} from '~/queries/schema/schema-general'

import { EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import type { ExperimentHealthCheckRuleApi, ExperimentHealthCheckResultApiValues } from '../generated/api.schemas'
import type { HealthPanelCheck } from './healthPanelChecks'

export type HealthCheckValues = ExperimentHealthCheckResultApiValues
export type HealthCheckRule = ExperimentHealthCheckRuleApi | ExperimentExposureHealthCheckRule

/**
 * One line of what a check read: a label and either a text or a time that the panel shows in the reader's zone. A
 * time that marks a start shows as a date, and the others show how long ago they were.
 */
export type HealthReading = { label: string } & ({ text: string } | { time: string; asDate?: boolean })

export interface HealthSplitRow {
    variant: string
    exposedCount: number
    exposedPercentage: number
    plannedPercentage: number | null
}

const HANDLING_LABELS: Record<string, string> = {
    exclude: 'Exclude from analysis',
    first_seen: 'Use first seen variant',
}

const TEST_LABELS: Record<NonNullable<HealthCheckRule['test']>, string> = {
    chi_squared: 'Chi-squared, exposed users against the planned split',
}

function numberValue(values: HealthCheckValues | undefined, key: string): number | null {
    const value = values?.[key]
    return typeof value === 'number' ? value : null
}

function formatCount(count: number): string {
    return humanFriendlyNumber(count, 0)
}

export function formatHealthPercentage(percentage: number): string {
    // One decimal would print a small share as 0%, which reads as none.
    return percentage > 0 && percentage < 0.1 ? 'less than 0.1%' : `${Number(percentage.toFixed(1))}%`
}

function formatPValue(pValue: number): string {
    return `p = ${Number(pValue.toPrecision(2))}`
}

function formatHours(hours: number): string {
    return hours < 48 ? `${Math.floor(hours)} hours` : `${Math.floor(hours / 24)} days`
}

function reading(label: string, text: string | null): HealthReading | null {
    return text === null ? null : { label, text }
}

function exposedReading(values: HealthCheckValues | undefined, units: string): HealthReading | null {
    const exposed = numberValue(values, 'exposed_count')
    return reading(`Exposed ${units}`, exposed === null ? null : formatCount(exposed))
}

function multipleVariantReading(values: HealthCheckValues | undefined): HealthReading | null {
    const count = numberValue(values, 'multiple_variant_count')
    const percentage = numberValue(values, 'multiple_variant_percentage')
    if (count === null) {
        return null
    }
    return reading(
        'In more than one variant',
        percentage === null ? formatCount(count) : `${formatCount(count)} · ${formatHealthPercentage(percentage)}`
    )
}

function calculatedMetricsReading(values: HealthCheckValues | undefined): HealthReading | null {
    const metricCount = numberValue(values, 'metric_count')
    const completedCount = numberValue(values, 'completed_metric_count')
    if (metricCount === null || completedCount === null) {
        return null
    }
    return reading('Metrics calculated', `${formatCount(completedCount)} of ${formatCount(metricCount)}`)
}

function flagReading(values: HealthCheckValues | undefined): HealthReading | null {
    if (typeof values?.flag_active !== 'boolean') {
        return null
    }
    const shipped = values.shipped_variant
    const text = values.flag_deleted
        ? 'Deleted'
        : !values.flag_active
          ? 'Off'
          : values.flag_rolled_out === false
            ? 'On, rolled out to 0%'
            : typeof shipped === 'string'
              ? `On, serves only "${shipped}"`
              : 'On'
    return reading('Feature flag', text)
}

/** What a check read, in the order the panel lists it. The p-value shows with the rule that judges it instead. */
export function healthCheckReadings(values: HealthCheckValues | undefined, units: string): HealthReading[] {
    const compared = numberValue(values, 'compared_count')
    const handling = values?.multiple_variant_handling
    const sinceLaunch = numberValue(values, 'since_launch_hours')
    const withoutFilter = numberValue(values, 'exposed_without_test_account_filter_count')
    const kept = numberValue(values, 'kept_by_test_account_filter_percentage')
    const onlyMatured = values?.only_count_matured_users
    const primaryMetrics = numberValue(values, 'primary_metric_count')
    const waitingMetrics = numberValue(values, 'waiting_metric_count')
    const failedMetrics = numberValue(values, 'failed_metric_count')
    const calculatedAt = values?.calculated_at

    return [
        exposedReading(values, units),
        reading(`${capitalizeFirstLetter(units)} compared`, compared === null ? null : formatCount(compared)),
        multipleVariantReading(values),
        reading(
            'Multiple variant handling',
            typeof handling === 'string' ? (HANDLING_LABELS[handling] ?? handling) : null
        ),
        reading('Since launch', sinceLaunch === null ? null : formatHours(sinceLaunch)),
        reading(
            `Exposed ${units} without the test account filters`,
            withoutFilter === null ? null : formatCount(withoutFilter)
        ),
        reading('Kept by the test account filters', kept === null ? null : formatHealthPercentage(kept)),
        reading(
            'Require completed conversion or retention window',
            typeof onlyMatured === 'boolean' ? (onlyMatured ? 'On' : 'Off') : null
        ),
        reading(
            "Primary metrics that can't count users yet",
            primaryMetrics === null || waitingMetrics === null
                ? null
                : `${formatCount(waitingMetrics)} of ${formatCount(primaryMetrics)}`
        ),
        calculatedMetricsReading(values),
        reading('Metrics whose calculation failed', failedMetrics === null ? null : formatCount(failedMetrics)),
        typeof calculatedAt === 'string' ? { label: 'Last calculated', time: calculatedAt } : null,
        flagReading(values),
    ].filter((line): line is HealthReading => line !== null)
}

function warnsWhen(rule: HealthCheckRule, units: string): string {
    const threshold = rule.threshold
    switch (rule.value) {
        case 'p_value':
            return `p is ${rule.warns} ${threshold}`
        case 'multiple_variant_percentage':
            return `${rule.warns === 'above' ? 'More' : 'Less'} than ${formatHealthPercentage(threshold)} of exposed ${units} are in more than one variant`
        case 'kept_by_test_account_filter_percentage':
            return `The test account filters keep ${rule.warns === 'above' ? 'more' : 'less'} than ${formatHealthPercentage(threshold)} of the exposed ${units}`
        case 'exposed_count':
            return rule.warns === 'below' && threshold === 1
                ? `No ${units} are exposed`
                : `${rule.warns === 'above' ? 'More' : 'Fewer'} than ${formatCount(threshold)} ${units} are exposed`
        default:
            return `${rule.value} is ${rule.warns} ${threshold}`
    }
}

function minimumAmount(minimum: NonNullable<HealthCheckRule['minimum']>, units: string): string {
    const amount = formatCount(minimum.threshold)
    switch (minimum.value) {
        case 'compared_count':
            return `${amount} ${units} compared`
        case 'multiple_variant_count':
            return `${amount} ${units} in more than one variant`
        case 'since_launch_hours':
            return `${amount} hours after launch`
        case 'exposed_without_test_account_filter_count':
            return `${amount} ${units} exposed without the test account filters`
        default:
            return `${amount} (${minimum.value})`
    }
}

/**
 * How a check decides, as label and text lines. A statistical test also shows its result here, but only for a check
 * that judged: a check that doesn't apply can still have read a p-value, which then decided nothing.
 */
export function healthRuleReadings(
    check: Pick<HealthPanelCheck, 'status' | 'values'>,
    rule: HealthCheckRule,
    units: string
): HealthReading[] {
    const result =
        check.status === 'passed' || check.status === 'finding' ? numberValue(check.values, rule.value) : null
    const lines: (HealthReading | null)[] = [
        rule.test ? { label: 'Test', text: TEST_LABELS[rule.test] } : null,
        rule.test && result !== null ? { label: 'Result', text: formatPValue(result) } : null,
        { label: 'Warns when', text: warnsWhen(rule, units) },
        rule.minimum ? { label: 'Warns from', text: minimumAmount(rule.minimum, units) } : null,
    ]
    return lines.filter((line): line is HealthReading => line !== null)
}

/** Whether the check shows the value that decided its status: the rule's value, from enough data to judge it. */
export function healthCheckShowsDecidingValue(check: Pick<HealthPanelCheck, 'values' | 'rule'>): boolean {
    const rule = check.rule
    if (!rule || numberValue(check.values, rule.value) === null) {
        return false
    }
    const minimumValue = rule.minimum ? numberValue(check.values, rule.minimum.value) : null
    return !rule.minimum || (minimumValue !== null && minimumValue >= rule.minimum.threshold)
}

/**
 * The exposed users of each compared variant against the planned split, from the exposure answer. The planned shares
 * come from the sample ratio test, so they are missing while too few users are exposed for it.
 */
export function healthExposureSplit(
    exposures: ExperimentExposureQueryResponse | null | undefined
): HealthSplitRow[] | null {
    const totals = exposures?.total_exposures
    if (!totals) {
        return null
    }
    const expected = exposures.sample_ratio_mismatch?.expected
    // The timeseries keeps the variant order of the experiment, which the totals don't.
    const ordered = exposures.timeseries?.length
        ? exposures.timeseries.map(({ variant }) => variant)
        : Object.keys(totals)
    const variants = ordered.filter((variant) =>
        expected ? variant in expected : variant !== EXPERIMENT_VARIANT_MULTIPLE
    )
    const comparedCount = variants.reduce((sum, variant) => sum + (totals[variant] ?? 0), 0)
    const plannedTotal = expected ? Object.values(expected).reduce((sum, count) => sum + count, 0) : 0
    if (variants.length < 2 || comparedCount === 0) {
        return null
    }
    return variants.map((variant) => ({
        variant,
        exposedCount: totals[variant] ?? 0,
        exposedPercentage: ((totals[variant] ?? 0) / comparedCount) * 100,
        plannedPercentage: expected && plannedTotal > 0 ? (expected[variant] / plannedTotal) * 100 : null,
    }))
}

function findCheck(checks: HealthPanelCheck[], key: HealthPanelCheck['key']): HealthPanelCheck | undefined {
    return checks.find((check) => check.key === key)
}

/** What the summary shows of the checks' values, from the checks that read each one. */
export function healthSummaryReadings(checks: HealthPanelCheck[], units: string): HealthReading[] {
    const srm = findCheck(checks, 'srm')
    const pValue = numberValue(srm?.values, 'p_value')
    const splitText =
        srm && pValue !== null && (srm.status === 'passed' || srm.status === 'finding')
            ? `${srm.status === 'passed' ? 'Matches' : "Doesn't match"}, ${formatPValue(pValue)}`
            : null
    return [
        exposedReading(findCheck(checks, 'zero_exposures')?.values, units),
        reading('Split against the plan', splitText),
        multipleVariantReading(findCheck(checks, 'multiple_variants_share')?.values),
        calculatedMetricsReading(findCheck(checks, 'metric_calculation_failed')?.values),
        flagReading(findCheck(checks, 'flag_state')?.values),
    ].filter((line): line is HealthReading => line !== null)
}
