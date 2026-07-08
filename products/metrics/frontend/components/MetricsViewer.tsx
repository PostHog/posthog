import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'

import {
    LemonButton,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { dayjs } from 'lib/dayjs'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'

import { DateMappingOption } from '~/types'

import { MetricNameFilter } from './MetricNameFilter'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { MetricsSeriesChart } from './MetricsSeriesChart'
import { MetricStatPanel } from './MetricStatPanel'
import {
    LIVE_REFRESH_MS,
    MetricAggregation,
    metricsViewerLogic,
    MetricsViewMode,
    RECOMMENDED_AGGREGATION_BY_TYPE,
} from './metricsViewerLogic'

const VIEW_MODE_OPTIONS: { value: MetricsViewMode; label: string }[] = [
    { value: 'chart', label: 'Chart' },
    { value: 'stat', label: 'Stat' },
]

// How the stat card summarizes the series into one headline value.
const SUMMARY_OPTIONS: { value: MetricSummary; label: string }[] = [
    { value: 'latest', label: 'Latest' },
    { value: 'average', label: 'Average' },
    { value: 'total', label: 'Total' },
]

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Count' },
    { value: 'p95', label: 'p95' },
    { value: 'rate', label: 'Rate (/s)' },
    { value: 'increase', label: 'Increase' },
]

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
        statSummary,
        groupByKeys,
        filterStrings,
        queryResults,
        sparklineValues,
        sparklineLabels,
        statTotal,
        anomalyBadge,
        liveRefresh,
        queryResultsLoading,
        savedInsightLoading,
        hasMetricName,
    } = useValues(logic)
    const {
        setMetricName,
        setAggregation,
        setDateFrom,
        setDateTo,
        setViewMode,
        setStatSummary,
        setGroupByKeys,
        setFilterStrings,
        setLiveRefresh,
        fetchQueryResults,
        fetchAnomaly,
        clearAnomaly,
        saveAsInsight,
    } = useActions(logic)
    const { items: pickerItems } = useValues(pickerLogic)

    // Refetch the chart whenever any filter changes — the loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [metricName, aggregation, dateFrom, dateTo, groupByKeys, filterStrings]) // eslint-disable-line react-hooks/exhaustive-deps

    // Characterize the recent window only while the stat card is visible — the badge is stat-mode only.
    useEffect(() => {
        if (viewMode === 'stat' && hasMetricName) {
            fetchAnomaly({})
        } else {
            clearAnomaly()
        }
    }, [metricName, aggregation, dateFrom, dateTo, viewMode, hasMetricName, filterStrings]) // eslint-disable-line react-hooks/exhaustive-deps

    const selectedMetricType = useMemo(
        () => pickerItems.find((item) => item.name === metricName)?.metric_type,
        [pickerItems, metricName]
    )
    const recommendedAggregation = selectedMetricType ? RECOMMENDED_AGGREGATION_BY_TYPE[selectedMetricType] : undefined

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
                <LemonInputSelect
                    mode="multiple"
                    size="small"
                    allowCustomValues
                    value={groupByKeys}
                    onChange={setGroupByKeys}
                    options={[]}
                    placeholder="Group by attribute…"
                    className="min-w-[12rem]"
                />
                <LemonInputSelect
                    mode="multiple"
                    size="small"
                    allowCustomValues
                    value={filterStrings}
                    onChange={setFilterStrings}
                    options={[]}
                    placeholder="Filter attribute=value…"
                    className="min-w-[14rem]"
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
                {viewMode === 'stat' && (
                    <LemonSelect
                        size="small"
                        value={statSummary}
                        options={SUMMARY_OPTIONS}
                        onChange={(value) => setStatSummary(value)}
                    />
                )}
                <LemonSwitch
                    label="Live"
                    checked={liveRefresh}
                    onChange={setLiveRefresh}
                    tooltip={`Auto-refresh every ${LIVE_REFRESH_MS / 1000}s`}
                    bordered
                />
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => saveAsInsight()}
                    loading={savedInsightLoading}
                    disabledReason={!hasMetricName ? 'Pick a metric first' : undefined}
                >
                    Save as insight
                </LemonButton>
            </div>
            <div className="relative h-[360px] border rounded p-3">
                {!hasMetricName ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        Pick a metric to see its time series.
                    </div>
                ) : hasResults && viewMode === 'stat' ? (
                    <MetricStatPanel
                        title={metricName}
                        summary={statSummary}
                        aggregation={aggregation}
                        total={statTotal}
                        values={sparklineValues}
                        labels={sparklineLabels.map(renderLabel)}
                        anomaly={anomalyBadge}
                    />
                ) : hasResults ? (
                    <MetricsSeriesChart
                        series={queryResults.map((s) => ({
                            labels: s.labels ?? {},
                            points: s.points,
                            metricName: s.metric_name,
                        }))}
                        fallbackName={metricName}
                        className="flex flex-col w-full h-full"
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
