import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'

import { LemonSegmentedButton, LemonSelect, SpinnerOverlay } from '@posthog/lemon-ui'
import { MetricCard, useChartTheme } from '@posthog/quill-charts'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import {
    computeMetricSummary,
    computeMetricSummaryChange,
    getMetricChangeTooltip,
    type MetricSummary,
    METRIC_SUMMARY_LABELS,
} from 'lib/components/Metric/metricSummary'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { DateMappingOption } from '~/types'

import { MetricNameFilter } from './MetricNameFilter'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { MetricAggregation, metricsViewerLogic, MetricsViewMode } from './metricsViewerLogic'

const VIEW_MODE_OPTIONS: { value: MetricsViewMode; label: string }[] = [
    { value: 'chart', label: 'Chart' },
    { value: 'stat', label: 'Stat' },
]

// The stat card shows a single headline value. 'latest' (the most recent bucket) is the natural
// default for a live metric; the user can switch total/average/latest in a later PR.
const STAT_SUMMARY: MetricSummary = 'latest'

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Count' },
    { value: 'p95', label: 'p95' },
]

// Recommended aggregation per OTel metric type. Used for an inline hint —
// we don't auto-switch the user's choice (hint, don't overwrite).
const RECOMMENDED_AGGREGATION_BY_TYPE: Record<string, MetricAggregation> = {
    gauge: 'avg',
    sum: 'sum',
    counter: 'sum',
    histogram: 'p95',
    summary: 'p95',
    exponential_histogram: 'p95',
}

// Mirrors the curated set used by `LogsViewer/Filters/DateRangeFilter`.
const DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Last 5 minutes',
        values: ['-5M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(5, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 30 minutes',
        values: ['-30M'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.subtract(30, 'minute').format(DATE_TIME_FORMAT),
        defaultInterval: 'minute',
    },
    {
        key: 'Last 1 hour',
        values: ['-1h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(1, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

export const MetricsViewer = (): JSX.Element => {
    const logic = metricsViewerLogic()
    // Keep the picker logic mounted alongside the viewer so the chosen metric's
    // metric_type stays available for the aggregation hint after the dropdown closes.
    const pickerLogic = useMountedLogic(metricNamePickerLogic())
    const {
        metricName,
        aggregation,
        dateFrom,
        dateTo,
        viewMode,
        sparklineValues,
        sparklineLabels,
        statTotal,
        queryResultsLoading,
        hasMetricName,
    } = useValues(logic)
    const { setMetricName, setAggregation, setDateFrom, setDateTo, setViewMode, fetchQueryResults } = useActions(logic)
    const { items: pickerItems } = useValues(pickerLogic)
    const chartTheme = useChartTheme()

    // Refetch the chart whenever any filter changes — the loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [metricName, aggregation, dateFrom, dateTo]) // eslint-disable-line react-hooks/exhaustive-deps

    const selectedMetricType = useMemo(
        () => pickerItems.find((item) => item.name === metricName)?.metric_type,
        [pickerItems, metricName]
    )
    const recommendedAggregation = selectedMetricType ? RECOMMENDED_AGGREGATION_BY_TYPE[selectedMetricType] : undefined

    // Mirrors the format/timeUnit ladder LogsSparkline uses so the X-axis density
    // matches the selected range.
    const { timeUnit, tickFormat } = useMemo(() => {
        if (!sparklineLabels.length) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        const first = dayjs(sparklineLabels[0])
        const last = dayjs(sparklineLabels[sparklineLabels.length - 1])
        const hoursDiff = last.diff(first, 'hours')
        if (hoursDiff <= 1) {
            return { timeUnit: 'second' as const, tickFormat: 'HH:mm:ss' }
        }
        if (hoursDiff <= 6) {
            return { timeUnit: 'minute' as const, tickFormat: 'HH:mm:ss' }
        }
        if (hoursDiff <= 48) {
            return { timeUnit: 'hour' as const, tickFormat: 'HH:mm' }
        }
        return { timeUnit: 'day' as const, tickFormat: 'D MMM HH:mm' }
    }, [sparklineLabels])

    const withXScale = useCallback(
        (scale: AnyScaleOptions): AnyScaleOptions =>
            ({
                ...scale,
                type: 'timeseries',
                ticks: {
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 6,
                    font: { size: 10, lineHeight: 1 },
                    callback: function (value: string | number) {
                        return dayjs(value).format(tickFormat)
                    },
                },
                time: { unit: timeUnit },
            }) as AnyScaleOptions,
        [timeUnit, tickFormat]
    )

    const renderLabel = useCallback((label: string): string => dayjs(label).format('D MMM YYYY HH:mm:ss'), [])

    const hasResults = sparklineValues.length > 0

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                    <MetricNameFilter value={metricName} onChange={setMetricName} />
                    {selectedMetricType && recommendedAggregation && aggregation !== recommendedAggregation && (
                        <span className="text-xs text-secondary">
                            {selectedMetricType} — {recommendedAggregation} recommended
                        </span>
                    )}
                </div>
                <LemonSelect
                    size="small"
                    value={aggregation}
                    options={AGGREGATION_OPTIONS}
                    onChange={(value) => setAggregation(value as MetricAggregation)}
                />
                <DateFilter
                    size="small"
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    dateOptions={DATE_OPTIONS}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setDateFrom(changedDateFrom)
                        setDateTo(changedDateTo)
                    }}
                    allowTimePrecision
                    allowFixedRangeWithTime
                    allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
                    use24HourFormat
                />
                <LemonSegmentedButton
                    size="small"
                    value={viewMode}
                    options={VIEW_MODE_OPTIONS}
                    onChange={(value) => setViewMode(value)}
                />
            </div>
            <div className="relative h-[360px] border rounded p-3">
                {!hasMetricName ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        Pick a metric to see its time series.
                    </div>
                ) : hasResults && viewMode === 'stat' ? (
                    <MetricCard
                        className="h-full"
                        title={metricName}
                        restingSubtitle={`${METRIC_SUMMARY_LABELS[STAT_SUMMARY]} · ${aggregation}`}
                        value={computeMetricSummary(STAT_SUMMARY, statTotal, sparklineValues)}
                        change={computeMetricSummaryChange(
                            STAT_SUMMARY,
                            { total: statTotal, data: sparklineValues },
                            undefined
                        )}
                        changeTooltip={getMetricChangeTooltip(STAT_SUMMARY, false, null)}
                        changeSize="md"
                        changeInline
                        hoverChangeFromPreviousPoint
                        data={sparklineValues}
                        labels={sparklineLabels.map(renderLabel)}
                        theme={chartTheme}
                        sparklineFill
                        sparklineHeight={140}
                        formatValue={(value) => humanFriendlyNumber(value)}
                        dataAttr="metrics-stat-value"
                    />
                ) : hasResults ? (
                    <Sparkline
                        type="line"
                        data={[{ name: aggregation, values: sparklineValues, color: 'data-color-1' }]}
                        labels={sparklineLabels}
                        className="w-full h-full"
                        withXScale={withXScale}
                        renderLabel={renderLabel}
                    />
                ) : !queryResultsLoading ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        No data for this metric in the selected range.
                    </div>
                ) : null}
                {queryResultsLoading && <SpinnerOverlay />}
            </div>
        </div>
    )
}
