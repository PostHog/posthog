import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    LemonButton,
    LemonBanner,
    LemonDropdown,
    LemonInputSelect,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    SpinnerOverlay,
    Tooltip,
} from '@posthog/lemon-ui'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'

import {
    AccessControlLevel,
    AccessControlResourceType,
    DateMappingOption,
    FilterLogicalOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { MetricNameFilter } from './MetricNameFilter'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { type MetricsExemplar } from './MetricsExemplarMarkers'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { MetricsSeriesChart } from './MetricsSeriesChart'
import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import {
    LIVE_REFRESH_MS,
    METRIC_FILTER_OPERATOR_ALLOWLIST,
    MetricAggregation,
    MetricsAnomalyBadge,
    metricsViewerLogic,
    RECOMMENDED_AGGREGATION_BY_TYPE,
} from './metricsViewerLogic'

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Series count' },
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
    const { openModal: openStarterDashboardModal } = useActions(metricsStarterDashboardLogic)
    const {
        metricName,
        aggregation,
        dateFrom,
        dateTo,
        groupByKeys,
        filterGroup,
        attributeEndpointFilters,
        chartSeries,
        anomalyBadge,
        liveRefresh,
        queryResultsLoading,
        queryError,
        savedInsightLoading,
        savedInsight,
        isAddToDashboardModalOpen,
        hasMetricName,
        hasResults,
    } = useValues(logic)
    const {
        setMetricName,
        setAggregation,
        setDateFrom,
        setDateTo,
        setFilterGroup,
        setLiveRefresh,
        fetchQueryResults,
        fetchAnomaly,
        clearAnomaly,
        saveAsInsight,
        addToDashboard,
        closeAddToDashboardModal,
    } = useActions(logic)
    const { items: pickerItems } = useValues(pickerLogic)
    const { traceExemplars } = useValues(metricsSamplesLogic)
    const { exemplarDotClicked } = useActions(metricsUsageTrackingLogic)
    const metricsViewerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Viewer
    )
    const insightEditorDisabledReason = getMetricsInsightEditorDisabledReason()
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )

    // Traced emissions as clickable dots along the bottom of the chart — the
    // metric->trace pivot without opening the Samples tab. Skipped entirely when
    // the user can't view traces, so a dot never leads to a dead end.
    const exemplarMarkers: MetricsExemplar[] = useMemo(
        () =>
            tracingDisabledReason
                ? []
                : traceExemplars.map((exemplar) => ({
                      timeMs: dayjs(exemplar.timestamp).valueOf(),
                      onClick: () => {
                          exemplarDotClicked(!!exemplar.spanId)
                          router.actions.push(
                              traceUrl({
                                  traceId: exemplar.traceId,
                                  spanId: exemplar.spanId || null,
                                  ts: exemplar.timestamp,
                              })
                          )
                      },
                  })),
        [traceExemplars, tracingDisabledReason, exemplarDotClicked]
    )

    // Refetch the chart whenever any filter changes — the loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [metricName, aggregation, dateFrom, dateTo, groupByKeys, filterGroup]) // eslint-disable-line react-hooks/exhaustive-deps

    // Characterize the recent window against the rest, so the chart carries a "vs baseline"
    // badge without the user having to eyeball the shape.
    useEffect(() => {
        if (hasMetricName) {
            fetchAnomaly({})
        } else {
            clearAnomaly()
        }
    }, [metricName, aggregation, dateFrom, dateTo, hasMetricName, filterGroup]) // eslint-disable-line react-hooks/exhaustive-deps

    const selectedMetricType = useMemo(
        () => pickerItems.find((item) => item.name === metricName)?.metric_type,
        [pickerItems, metricName]
    )
    const recommendedAggregation = selectedMetricType ? RECOMMENDED_AGGREGATION_BY_TYPE[selectedMetricType] : undefined

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
                {/* The filter bar is the primary control, mirroring logs and traces. */}
                <div className="flex flex-wrap items-center gap-2 justify-between">
                    <div className="flex flex-1 flex-wrap items-center gap-2 min-w-[16rem]">
                        <div className="flex flex-col gap-1">
                            <MetricNameFilter
                                value={metricName}
                                onChange={setMetricName}
                                disabled={!!metricsViewerDisabledReason}
                                disabledReason={metricsViewerDisabledReason}
                            />
                            {selectedMetricType && recommendedAggregation && aggregation !== recommendedAggregation && (
                                <span className="text-xs text-secondary">
                                    {selectedMetricType} — {recommendedAggregation} recommended
                                </span>
                            )}
                        </div>
                        <UniversalFilters
                            rootKey="metrics-viewer-filters"
                            group={filterGroup.values[0] as UniversalFiltersGroup}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.MetricAttributes]}
                            endpointFilters={attributeEndpointFilters}
                            onChange={(group) => {
                                if (!metricsViewerDisabledReason) {
                                    setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })
                                }
                            }}
                        >
                            <MetricsViewerFilterBar disabledReason={metricsViewerDisabledReason} />
                        </UniversalFilters>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
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
                            disabledReason={metricsViewerDisabledReason}
                        />
                        <LemonSwitch
                            label="Auto-refresh"
                            checked={liveRefresh}
                            onChange={setLiveRefresh}
                            tooltip={`Refreshes every ${LIVE_REFRESH_MS / 1000}s`}
                            bordered
                            data-attr="metrics-viewer-live-toggle"
                            disabledReason={metricsViewerDisabledReason}
                        />
                    </div>
                </div>
                {/* Aggregation and grouping controls sit below the filter bar. */}
                <div className="flex flex-wrap items-center gap-2 justify-between">
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSelect
                            size="small"
                            value={aggregation}
                            options={AGGREGATION_OPTIONS}
                            onChange={(value) => setAggregation(value as MetricAggregation)}
                            data-attr="metrics-viewer-aggregation"
                            disabledReason={metricsViewerDisabledReason}
                        />
                        <MetricsGroupByButton disabledReason={metricsViewerDisabledReason} />
                        {anomalyBadge && <MetricsAnomalyTag anomaly={anomalyBadge} />}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => saveAsInsight()}
                            loading={savedInsightLoading}
                            disabledReason={
                                insightEditorDisabledReason ?? (!hasMetricName ? 'Pick a metric first' : undefined)
                            }
                        >
                            Save as insight
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={() => addToDashboard()}
                            loading={savedInsightLoading}
                            disabledReason={
                                insightEditorDisabledReason ?? (!hasMetricName ? 'Pick a metric first' : undefined)
                            }
                            data-attr="metrics-viewer-add-to-dashboard"
                        >
                            Add to dashboard
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={openStarterDashboardModal}
                            tooltip="Create a dashboard with one insight per metric, using each metric's recommended aggregation"
                            data-attr="metrics-viewer-starter-dashboard"
                            disabledReason={insightEditorDisabledReason}
                        >
                            New service dashboard
                        </LemonButton>
                    </div>
                </div>
            </div>
            <MetricsStarterDashboardModal />
            {savedInsight && (
                <>
                    <AddToDashboardModal
                        isOpen={isAddToDashboardModalOpen}
                        closeModal={closeAddToDashboardModal}
                        insightProps={{ dashboardItemId: savedInsight.short_id, cachedInsight: savedInsight }}
                        canEditInsight={!insightEditorDisabledReason}
                        data-attr="metrics-viewer-add-to-dashboard-modal"
                    />
                    {/* The picker's "Add to a new dashboard" only opens this dialog, so the two
                        have to be rendered together (as the insight scene does). */}
                    <NewDashboardModal />
                </>
            )}
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
                        ) : hasResults ? (
                            <MetricsSeriesChart
                                series={chartSeries}
                                fallbackName={metricName}
                                exemplars={exemplarMarkers}
                            />
                        ) : !queryResultsLoading ? (
                            <div className="h-full flex items-center justify-center text-secondary text-sm">
                                No data for this metric in the selected range.
                            </div>
                        ) : null}
                        {queryResultsLoading && <SpinnerOverlay />}
                    </div>
                </div>
                {hasMetricName && (
                    <div className="xl:w-[26rem] shrink-0 xl:max-h-[360px] flex flex-col">
                        <MetricsSamplesPanel />
                    </div>
                )}
            </div>
        </div>
    )
}

// How the recent slice of the window compares against the rest of it, sitting next to the
// controls that define the window rather than over the chart, where it would fight the legend.
const MetricsAnomalyTag = ({ anomaly }: { anomaly: MetricsAnomalyBadge }): JSX.Element => (
    <Tooltip
        title={`Baseline ${humanFriendlyNumber(anomaly.baselineMean)} → recent ${humanFriendlyNumber(
            anomaly.anomalyMean
        )}${anomaly.onsetTime ? `, onset ${dayjs(anomaly.onsetTime).format('D MMM HH:mm')}` : ''}`}
    >
        <LemonTag type="warning" data-attr="metrics-viewer-anomaly-badge">
            {anomaly.direction === 'up' ? '▲' : '▼'} {anomaly.percent}% vs baseline
        </LemonTag>
    </Tooltip>
)

// Filter chips + "Add filter" button, mirroring the logs viewer's applied-filters row: picking an
// attribute opens the chip for value selection, with suggestions fed by the metrics attribute endpoints.
const MetricsViewerFilterBar = ({ disabledReason }: { disabledReason: string | null }): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <div className="flex flex-wrap items-center gap-1">
            {filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) =>
                // This UI only ever adds leaf filters, so nested groups can't occur here.
                isUniversalGroupFilterLike(filterOrGroup) ? null : (
                    <span
                        key={index}
                        title={disabledReason ?? undefined}
                        className={disabledReason ? 'pointer-events-none opacity-50' : undefined}
                    >
                        <UniversalFilters.Value
                            index={index}
                            filter={filterOrGroup}
                            onRemove={disabledReason ? undefined : () => removeGroupValue(index)}
                            onChange={(value) => {
                                if (!disabledReason) {
                                    replaceGroupValue(index, value)
                                }
                            }}
                            initiallyOpen={allowInitiallyOpen && !disabledReason}
                            operatorAllowlist={METRIC_FILTER_OPERATOR_ALLOWLIST}
                        />
                    </span>
                )
            )}
            <UniversalFilters.AddFilterButton
                size="small"
                type="secondary"
                title="Filter"
                disabledReason={disabledReason}
            />
        </div>
    )
}

// Group by is a button that opens the attribute multiselect, so the filter bar stays the
// primary control (mirrors how logs and traces keep grouping as a button, not the main bar).
const MetricsGroupByButton = ({ disabledReason }: { disabledReason: string | null }): JSX.Element => {
    const { groupByKeys, attributeKeyOptions, attributeKeyOptionsLoading } = useValues(metricsViewerLogic)
    const { setGroupByKeys, setGroupBySearch, loadAttributeKeyOptions } = useActions(metricsViewerLogic)
    const [open, setOpen] = useState<boolean>(false)

    const label =
        groupByKeys.length === 0
            ? 'Group by'
            : groupByKeys.length === 1
              ? `Group by: ${groupByKeys[0]}`
              : `Group by: ${groupByKeys.length} attributes`

    return (
        <LemonDropdown
            visible={open}
            closeOnClickInside={false}
            onClickOutside={() => setOpen(false)}
            overlay={
                <div className="p-1 w-[18rem]">
                    <LemonInputSelect
                        mode="multiple"
                        size="small"
                        allowCustomValues
                        value={groupByKeys}
                        onChange={setGroupByKeys}
                        options={attributeKeyOptions}
                        loading={attributeKeyOptionsLoading}
                        onInputChange={setGroupBySearch}
                        onFocus={() => loadAttributeKeyOptions({})}
                        placeholder="Group by attribute…"
                        data-attr="metrics-viewer-group-by"
                        disabledReason={disabledReason}
                        autoFocus
                    />
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                active={open || groupByKeys.length > 0}
                sideIcon={<IconChevronDown />}
                onClick={() => {
                    setOpen((wasOpen) => !wasOpen)
                    loadAttributeKeyOptions({})
                }}
                disabledReason={disabledReason ?? undefined}
                data-attr="metrics-viewer-group-by-button"
                // Attribute keys can be long, so cap the trigger rather than let it push the row wide
                truncate
                className="max-w-[16rem]"
                tooltip={groupByKeys.length > 0 ? groupByKeys.join(', ') : undefined}
            >
                {label}
            </LemonButton>
        </LemonDropdown>
    )
}
