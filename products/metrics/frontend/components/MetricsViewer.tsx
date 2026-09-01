import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    SpinnerOverlay,
} from '@posthog/lemon-ui'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DATE_TIME_FORMAT, formatDateRange } from 'lib/utils/datetime'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { urls } from 'scenes/urls'

import type { MetricsDisplayType } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, DateMappingOption } from '~/types'

import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { getMetricsInsightEditorDisabledReason } from '../metricsAccess'
import { MetricsAnomalyPanel } from './MetricsAnomalyPanel'
import { MetricsChartSettings } from './MetricsChartSettings'
import { MetricsClauseRow } from './MetricsClauseRow'
import { type MetricsExemplar } from './MetricsExemplarMarkers'
import { MetricsLogsSourceTag } from './MetricsLogsSourceTag'
import { MetricsRelatedMenu } from './MetricsRelatedMenu'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { MetricsSamplesPanel } from './MetricsSamplesPanel'
import { MetricsSeriesChart } from './MetricsSeriesChart'
import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'
import { MetricsStarterDashboardModal } from './MetricsStarterDashboardModal'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { LIVE_REFRESH_MS, MAX_CLAUSES, metricsViewerLogic, sanitizeFormulaInput } from './metricsViewerLogic'

// `stat` is in the schema but has no renderer yet, so the picker doesn't offer it.
const DISPLAY_TYPE_OPTIONS: { value: MetricsDisplayType; label: string }[] = [
    { value: 'line', label: 'Line' },
    { value: 'area', label: 'Area' },
    { value: 'bar', label: 'Bar' },
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
    // The side panel's logic listens to this viewer's filter changes; mounting it
    // here keeps samples in sync even while the panel itself is off-screen.
    useMountedLogic(metricsSamplesLogic())
    const { openModal: openStarterDashboardModal } = useActions(metricsStarterDashboardLogic)
    const {
        viewerClauses,
        activeClauseIndex,
        formula,
        queryFingerprint,
        anomalyFingerprint,
        metricName,
        dateFrom,
        dateTo,
        chartSeries,
        anomalyBadge,
        liveRefresh,
        queryLoading,
        queryError,
        savedInsightLoading,
        savedInsight,
        isAddToDashboardModalOpen,
        hasMetricName,
        hasResults,
        displayType,
        metricsDisplay,
    } = useValues(logic)
    const {
        setDateFrom,
        setDateTo,
        setLiveRefresh,
        addClause,
        fetchQueryResults,
        fetchAnomaly,
        clearAnomaly,
        saveAsInsight,
        addToDashboard,
        closeAddToDashboardModal,
        setDisplayType,
    } = useActions(logic)
    const { traceExemplars, errorSpikes, showErrorSpikes } = useValues(metricsSamplesLogic)
    const { toggleShowErrorSpikes } = useActions(metricsSamplesLogic)
    // Staff-only PoC gate, layered on top of the wider metrics alpha flag.
    const errorOverlaysEnabled = useFeatureFlag('METRICS_ERROR_OVERLAYS')
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
    const errorTrackingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.ErrorTracking,
        AccessControlLevel.Viewer
    )

    // Clickable dots along the bottom of the chart: traced emissions (the
    // metric->trace pivot) and Error Tracking issue spikes (team-wide — spike
    // events carry no service attribution). Each kind is skipped entirely when
    // the user can't view its target product, so a dot never leads to a dead
    // end. One memo, so the chart prop keeps a stable identity across renders.
    const chartMarkers: MetricsExemplar[] = useMemo(() => {
        const traceMarkers: MetricsExemplar[] = tracingDisabledReason
            ? []
            : traceExemplars.map((exemplar) => ({
                  timeMs: dayjs(exemplar.timestamp).valueOf(),
                  tooltipLabel: `Traced emission at ${dayjs(exemplar.timestamp).format('D MMM HH:mm:ss')}. Click to view the trace.`,
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
              }))
        const spikeMarkers: MetricsExemplar[] =
            !errorOverlaysEnabled || errorTrackingDisabledReason
                ? []
                : errorSpikes.map((spike) => ({
                      timeMs: dayjs(spike.detected_at).valueOf(),
                      color: 'danger',
                      tooltipLabel: `Error spike at ${dayjs(spike.detected_at).format('D MMM HH:mm:ss')}: ${spike.issue_name ?? 'Untitled issue'}. Click to view the issue.`,
                      onClick: () => {
                          router.actions.push(urls.errorTrackingIssue(spike.issue_id, { timestamp: spike.detected_at }))
                      },
                  }))
        return [...traceMarkers, ...spikeMarkers]
    }, [
        traceExemplars,
        tracingDisabledReason,
        exemplarDotClicked,
        errorSpikes,
        errorOverlaysEnabled,
        errorTrackingDisabledReason,
    ])

    // Refetch the chart whenever the effective query changes — the fingerprints are
    // strings, so edits that don't change the request (a blank just-added row, a
    // group-by tweak the anomaly body doesn't carry) don't refire the effects.
    // The loader breakpoint debounces input.
    useEffect(() => {
        fetchQueryResults({})
    }, [queryFingerprint, dateFrom, dateTo]) // eslint-disable-line react-hooks/exhaustive-deps

    // Characterize the recent window against the rest, so the chart carries a "vs baseline"
    // badge without the user having to eyeball the shape. The loader suppresses the badge
    // for multi-series and formula queries, where no single input series describes the chart.
    useEffect(() => {
        if (hasMetricName) {
            fetchAnomaly({})
        } else {
            clearAnomaly()
        }
    }, [anomalyFingerprint, dateFrom, dateTo, hasMetricName]) // eslint-disable-line react-hooks/exhaustive-deps

    const showFormulaInput = viewerClauses.length > 1 || formula !== ''

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-start gap-2 justify-between">
                    <div className="flex flex-col gap-2 flex-1 min-w-[16rem]">
                        {viewerClauses.map((clause, index) => (
                            <MetricsClauseRow
                                key={clause.name}
                                clause={clause}
                                index={index}
                                isActive={index === activeClauseIndex}
                                showAlias={viewerClauses.length > 1}
                                disabledReason={metricsViewerDisabledReason}
                            />
                        ))}
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                size="small"
                                type="secondary"
                                icon={<IconPlusSmall />}
                                onClick={() => addClause()}
                                disabledReason={
                                    metricsViewerDisabledReason ??
                                    (viewerClauses.length >= MAX_CLAUSES
                                        ? `A query can have at most ${MAX_CLAUSES} series`
                                        : undefined)
                                }
                                data-attr="metrics-viewer-add-series"
                            >
                                Add series
                            </LemonButton>
                            {showFormulaInput && <MetricsFormulaInput disabledReason={metricsViewerDisabledReason} />}
                        </div>
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
                        {/* Hidden (not disabled) without Error Tracking view access, so the
                            toggle never references a product the user cannot see. */}
                        {errorOverlaysEnabled && !errorTrackingDisabledReason && (
                            <LemonSwitch
                                label="Error spikes"
                                checked={showErrorSpikes}
                                onChange={toggleShowErrorSpikes}
                                tooltip="Mark Error Tracking issue spikes on the chart (team-wide, PoC)"
                                bordered
                                data-attr="metrics-viewer-error-spikes-toggle"
                                disabledReason={metricsViewerDisabledReason}
                            />
                        )}
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 justify-between">
                    <div className="flex flex-wrap items-center gap-2">
                        <LemonSelect
                            size="small"
                            value={displayType}
                            options={DISPLAY_TYPE_OPTIONS}
                            onChange={setDisplayType}
                            data-attr="metrics-viewer-display-type"
                            disabledReason={metricsViewerDisabledReason}
                        />
                        <MetricsChartSettings />
                        <MetricsRelatedMenu />
                        {anomalyBadge && <MetricsAnomalyPanel anomaly={anomalyBadge} />}
                        <MetricsLogsSourceTag metricName={metricName} />
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
                                fallbackName={formula || metricName || 'metric'}
                                display={metricsDisplay}
                                exemplars={chartMarkers}
                            />
                        ) : !queryLoading ? (
                            <div className="h-full flex items-center justify-center text-secondary text-sm">
                                No data for this metric in the selected range.
                            </div>
                        ) : null}
                        {queryLoading && <SpinnerOverlay />}
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

// Committed on blur/Enter (mirroring TrendsFormula) so a half-typed formula doesn't fire
// a query per keystroke. Input is lowercased — clause aliases are lowercase and the
// backend parser is case-sensitive.
const MetricsFormulaInput = ({ disabledReason }: { disabledReason: string | null }): JSX.Element => {
    const { formula } = useValues(metricsViewerLogic)
    const { setFormula } = useActions(metricsViewerLogic)
    const [draft, setDraft] = useState(formula)

    // An external change (URL restore, clause reset) replaces the local draft.
    useEffect(() => {
        setDraft(formula)
    }, [formula])

    const commit = (): void => {
        if (draft !== formula) {
            setFormula(draft)
        }
    }

    return (
        <Tooltip title="Arithmetic over the series letters, with + - * / and parentheses. Only the formula result is charted.">
            <LemonInput
                size="small"
                className="min-w-48"
                value={draft}
                onChange={(value) => setDraft(sanitizeFormulaInput(value))}
                onBlur={commit}
                onPressEnter={commit}
                placeholder="Formula, e.g. (a - b) / a"
                data-attr="metrics-viewer-formula"
                disabledReason={disabledReason}
            />
        </Tooltip>
    )
}
