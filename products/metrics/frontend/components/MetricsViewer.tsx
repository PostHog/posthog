import { useActions, useMountedLogic, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
    LemonBanner,
    LemonInputSelect,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { type MetricSummary } from 'lib/components/Metric/metricSummary'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'

import { DateMappingOption, FilterLogicalOperator, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import { MetricNameFilter } from './MetricNameFilter'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { MetricsChartLegend } from './MetricsChartLegend'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { MetricStatPanel } from './MetricStatPanel'
import {
    LIVE_REFRESH_MS,
    METRIC_FILTER_OPERATOR_ALLOWLIST,
    MetricAggregation,
    metricsViewerLogic,
    MetricsViewMode,
    RECOMMENDED_AGGREGATION_BY_TYPE,
} from './metricsViewerLogic'

const VIEW_MODE_OPTIONS: { value: MetricsViewMode; label: string; 'data-attr': string }[] = [
    { value: 'chart', label: 'Chart', 'data-attr': 'metrics-viewer-view-mode-chart' },
    { value: 'stat', label: 'Stat', 'data-attr': 'metrics-viewer-view-mode-stat' },
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
    // The side panel's logic listens to this viewer's filter changes; mounting it
    // here keeps samples in sync even while the panel itself is off-screen.
    useMountedLogic(metricsSamplesLogic())
    const {
        metricName,
        aggregation,
        dateFrom,
        dateTo,
        viewMode,
        statSummary,
        groupByKeys,
        filterGroup,
        attributeEndpointFilters,
        chartSeries,
        sparklineValues,
        sparklineLabels,
        statTotal,
        anomalyBadge,
        liveRefresh,
        queryResultsLoading,
        queryError,
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
        setFilterGroup,
        setLiveRefresh,
        fetchQueryResults,
        fetchAnomaly,
        clearAnomaly,
    } = useActions(logic)
    const { items: pickerItems } = useValues(pickerLogic)

    // Refetch the chart whenever any filter changes — the loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [metricName, aggregation, dateFrom, dateTo, groupByKeys, filterGroup]) // eslint-disable-line react-hooks/exhaustive-deps

    // Characterize the recent window only while the stat card is visible — the badge is stat-mode only.
    useEffect(() => {
        if (viewMode === 'stat' && hasMetricName) {
            fetchAnomaly({})
        } else {
            clearAnomaly()
        }
    }, [metricName, aggregation, dateFrom, dateTo, viewMode, hasMetricName, filterGroup]) // eslint-disable-line react-hooks/exhaustive-deps

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
                    data-attr="metrics-viewer-aggregation"
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
                    data-attr="metrics-viewer-group-by"
                />
                <UniversalFilters
                    rootKey="metrics-viewer-filters"
                    group={filterGroup.values[0] as UniversalFiltersGroup}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
                    endpointFilters={attributeEndpointFilters}
                    onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
                >
                    <MetricsViewerFilterBar />
                </UniversalFilters>
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
                        data-attr="metrics-viewer-stat-summary"
                    />
                )}
                <LemonSwitch
                    label="Live"
                    checked={liveRefresh}
                    onChange={setLiveRefresh}
                    tooltip={`Auto-refresh every ${LIVE_REFRESH_MS / 1000}s`}
                    bordered
                    data-attr="metrics-viewer-live-toggle"
                />
            </div>
            <div className="flex flex-col xl:flex-row gap-3 items-stretch">
                <div className="flex-1 min-w-0">
                    <div className="relative h-[360px] border rounded p-3">
                        {!hasMetricName ? (
                            <div className="h-full flex items-center justify-center text-secondary text-sm">
                                Pick a metric to see its time series.
                            </div>
                        ) : queryError ? (
                            <div className="h-full flex items-center justify-center">
                                <LemonBanner type="error" className="max-w-md">
                                    {queryError}
                                </LemonBanner>
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
                            <Sparkline
                                type="line"
                                data={chartSeries}
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
                    {viewMode === 'chart' && hasResults && <MetricsChartLegend series={chartSeries} />}
                </div>
                {viewMode === 'chart' && hasMetricName && (
                    <div className="xl:w-[26rem] shrink-0 xl:max-h-[360px] flex flex-col">
                        <MetricsSamplesPanel />
                    </div>
                )}
            </div>
        </div>
    )
}

// Filter chips + "Add filter" button, mirroring the logs viewer's applied-filters row: picking an
// attribute opens the chip for value selection, with suggestions fed by the metrics attribute endpoints.
const MetricsViewerFilterBar = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <div className="flex flex-wrap items-center gap-1">
            {filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) =>
                // This UI only ever adds leaf filters, so nested groups can't occur here.
                isUniversalGroupFilterLike(filterOrGroup) ? null : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen}
                        operatorAllowlist={METRIC_FILTER_OPERATOR_ALLOWLIST}
                    />
                )
            )}
            <UniversalFilters.AddFilterButton size="small" type="secondary" title="Filter" />
        </div>
    )
}
