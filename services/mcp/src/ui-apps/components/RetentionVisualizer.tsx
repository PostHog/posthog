import { type ReactElement, useMemo, useState } from 'react'

import { EmptyState } from '@posthog/mosaic'

import { BarChart, LineChart, Select, type Series } from './charts'
import type {
    RetentionAggregationType,
    RetentionPeriod,
    RetentionReference,
    RetentionResult,
    RetentionResultItem,
    RetentionVisualizerProps,
} from './types'

type ChartMode = 'line' | 'bar'

const CHART_MODE_OPTIONS = [
    { value: 'line' as const, label: 'Line' },
    { value: 'bar' as const, label: 'Bar' },
]

function formatStartDate(cohort: RetentionResultItem, period: RetentionPeriod): string | null {
    if (!cohort.date) {
        return null
    }
    const d = new Date(cohort.date)
    if (Number.isNaN(d.getTime())) {
        return null
    }
    if (period === 'Hour') {
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric' })
    }
    if (period === 'Month') {
        return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    }
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatCohortLegendLabel(cohort: RetentionResultItem, cohortNumber: number, period: RetentionPeriod): string {
    const startDate = formatStartDate(cohort, period)
    const breakdown =
        cohort.breakdown_value !== undefined && cohort.breakdown_value !== null && cohort.breakdown_value !== ''
            ? String(cohort.breakdown_value)
            : null
    const base = `Cohort ${cohortNumber}`
    if (breakdown) {
        return startDate ? `${base} (${breakdown}, ${startDate})` : `${base} (${breakdown})`
    }
    return startDate ? `${base} (${startDate})` : base
}

// Mirrors the math in `retentionLogic.ts`: each cohort's interval values become a percentage of the
// reference cohort size (`total` = day-0, `previous` = preceding interval). For non-count aggregations
// we surface `aggregation_value` directly without normalization.
function computeSeriesValue(
    values: RetentionResultItem['values'],
    intervalIndex: number,
    aggregationType: RetentionAggregationType,
    reference: RetentionReference
): number {
    const current = values[intervalIndex]
    if (!current) {
        return 0
    }
    if (aggregationType !== 'count') {
        return current.aggregation_value ?? 0
    }
    if (reference === 'previous') {
        if (intervalIndex === 0) {
            return 100
        }
        const prev = values[intervalIndex - 1]
        if (!prev || prev.count === 0) {
            return 0
        }
        return (current.count / prev.count) * 100
    }
    const baseline = values[0]?.count ?? 0
    if (baseline === 0) {
        return 0
    }
    return (current.count / baseline) * 100
}

function buildXAxisLabels(numIntervals: number, period: RetentionPeriod): string[] {
    return Array.from({ length: numIntervals }, (_, i) => `${period} ${i}`)
}

// Sort chronologically so "Cohort 1" is the earliest start date. Cohorts without a parseable date
// preserve their original order at the end of the list.
function sortCohorts(results: RetentionResult): RetentionResult {
    return [...results].sort((a, b) => {
        const ta = a.date ? new Date(a.date).getTime() : Number.POSITIVE_INFINITY
        const tb = b.date ? new Date(b.date).getTime() : Number.POSITIVE_INFINITY
        // `ta`/`tb` can each be a finite ms timestamp, NaN (invalid `date`), or POSITIVE_INFINITY
        // (missing `date`). `ta - tb` returns NaN whenever both are non-finite (Inf-Inf or NaN-*),
        // which violates the sort comparator contract — handle those pairings explicitly.
        const aMissing = Number.isNaN(ta) || !Number.isFinite(ta)
        const bMissing = Number.isNaN(tb) || !Number.isFinite(tb)
        if (aMissing && bMissing) {
            return 0
        }
        if (aMissing) {
            return 1
        }
        if (bMissing) {
            return -1
        }
        return ta - tb
    })
}

// Cap at the size of the shared chart palette so each cohort gets its own distinct color rather
// than cycling — beyond this the lines blur into noise anyway.
const MAX_COHORTS = 8

export function RetentionVisualizer({ query, results }: RetentionVisualizerProps): ReactElement {
    const aggregationType: RetentionAggregationType = query?.retentionFilter?.aggregationType ?? 'count'
    const reference: RetentionReference = query?.retentionFilter?.retentionReference ?? 'total'
    const period: RetentionPeriod = query?.retentionFilter?.period ?? 'Day'
    const isPercentage = aggregationType === 'count'

    const [chartMode, setChartMode] = useState<ChartMode>('line')

    const { series, labels, maxValue, totalCohorts } = useMemo(() => {
        if (!results || results.length === 0) {
            return { series: [] as Series[], labels: [] as string[], maxValue: 0, totalCohorts: 0 }
        }
        const sorted = sortCohorts(results)
        // Cap to MAX_COHORTS so each line gets a distinct palette color rather than wrapping back
        // to the first color. Older cohorts have the most observed intervals so we keep those.
        const limited = sorted.slice(0, MAX_COHORTS)
        const numIntervals = limited.reduce((m, c) => Math.max(m, c.values.length), 0)
        const xLabels = buildXAxisLabels(numIntervals, period)
        let computedMax = 0

        const built: Series[] = limited.map((cohort, idx) => {
            const points = Array.from({ length: numIntervals }, (_, i) => {
                const y = computeSeriesValue(cohort.values, i, aggregationType, reference)
                if (y > computedMax) {
                    computedMax = y
                }
                return { x: i, y, label: xLabels[i] ?? `${i}` }
            })
            return {
                label: formatCohortLegendLabel(cohort, idx + 1, period),
                points,
            }
        })

        return {
            series: built,
            labels: xLabels,
            maxValue: computedMax || 1,
            totalCohorts: sorted.length,
        }
    }, [results, aggregationType, reference, period])

    if (!results || results.length === 0 || series.length === 0 || labels.length === 0) {
        return <EmptyState icon="chart" description="No retention data available" />
    }

    const yAxisLabel = isPercentage ? 'Retention %' : aggregationType === 'sum' ? 'Sum' : 'Avg'
    const truncationNotice =
        totalCohorts > MAX_COHORTS ? `Showing first ${MAX_COHORTS} of ${totalCohorts} cohorts (oldest first)` : null

    return (
        <div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: '0.5rem',
                }}
            >
                <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary, #6b7280)' }}>
                    {truncationNotice}
                </span>
                {/* eslint-disable-next-line react/forbid-elements */}
                <Select value={chartMode} onChange={setChartMode} options={CHART_MODE_OPTIONS} />
            </div>
            {chartMode === 'bar' ? (
                <BarChart series={series} labels={labels} maxValue={maxValue} yAxisLabel={yAxisLabel} />
            ) : (
                <LineChart series={series} labels={labels} maxValue={maxValue} yAxisLabel={yAxisLabel} />
            )}
        </div>
    )
}
