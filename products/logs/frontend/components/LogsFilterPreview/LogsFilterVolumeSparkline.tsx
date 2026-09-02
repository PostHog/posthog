import { useActions, useValues } from 'kea'
import { useEffect, useId, useMemo } from 'react'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import type { GoalLineConfig, Series, TimeInterval, TimeSeriesBarChartConfig } from '@posthog/quill-charts'
import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { resolveVariableColor } from 'lib/charts/utils/color'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { UniversalFiltersGroup } from '~/types'

import {
    DEFAULT_PREVIEW_LOOKBACK,
    LogsFilterPreviewLookback,
    LogsFilterPreviewMetric,
    LogsFilterPreviewPoint,
    LogsFilterPreviewSeriesData,
    SPARKLINE_ROW_LIMIT,
    TOP_SERVICES_LIMIT,
    buildSparklineSeries,
    formatBytes,
} from './logsFilterVolumePreview'
import { logsFilterVolumePreviewLogic } from './logsFilterVolumePreviewLogic'

export interface LogsFilterVolumeSparklineRenderInfo extends LogsFilterPreviewSeriesData {
    points: LogsFilterPreviewPoint[] | null
    /** The response hit the backend row cap, so the newest buckets are missing. */
    truncated: boolean
}

export interface LogsFilterVolumeSparklineProps {
    filterGroup: UniversalFiltersGroup
    metric: LogsFilterPreviewMetric
    /** How far back the preview looks; defaults to the last 24h. */
    lookback?: LogsFilterPreviewLookback
    /** Overrides the auto-generated logic key; only needed by stories and tests. */
    previewKey?: string
    /** Threshold lines in the chart's own units, which depend on the resolved bucket width. */
    buildGoalLines?: (info: LogsFilterVolumeSparklineRenderInfo) => GoalLineConfig[] | undefined
    /** Rendered under the chart once data has loaded (rate-limit note, retention projection). */
    renderCaption?: (info: LogsFilterVolumeSparklineRenderInfo) => JSX.Element | null
}

/** Granularity of the date ticks and the tooltip header. The backend picks the bucket width from
 *  the queried range, so read it off the data rather than assuming half-hour buckets. */
function bucketInterval(bucketSeconds: number): TimeInterval {
    if (bucketSeconds >= 86400) {
        return 'day'
    }
    return bucketSeconds >= 3600 ? 'hour' : 'minute'
}

/**
 * Live preview of the log volume a filter group matches over the last 24h, broken down by service.
 * Shared by the drop-rule and retention-rule editors — one request serves both metrics, since each
 * row carries `count` and `bytes_uncompressed`.
 */
export function LogsFilterVolumeSparkline({
    filterGroup,
    metric,
    lookback = DEFAULT_PREVIEW_LOOKBACK,
    previewKey,
    buildGoalLines,
    renderCaption,
}: LogsFilterVolumeSparklineProps): JSX.Element {
    const generatedKey = useId()
    const logic = logsFilterVolumePreviewLogic({ previewKey: previewKey ?? generatedKey })
    const { filterPreview, filterPreviewLoading } = useValues(logic)
    const { setPreviewRequest, refreshFilterPreview } = useActions(logic)
    const theme = useChartTheme()

    const hasFilters = filterGroup.values.length > 0

    // Serialized so a re-render handing us a fresh-but-equal object doesn't re-fire the request.
    // Mounting runs this too, which covers the edit-mode case of opening a form with filters already set.
    // `metric` is a dependency because the backend ranks by it before collapsing the tail, so
    // switching metric needs a fresh request to get the right top-N back. `lookback` changes the
    // queried window, so it needs a fresh request too.
    const serializedFilterGroup = useMemo(() => JSON.stringify(filterGroup), [filterGroup])
    useEffect(() => {
        setPreviewRequest(filterGroup, metric, lookback)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [serializedFilterGroup, metric, lookback])

    const seriesData = useMemo(() => buildSparklineSeries(filterPreview, metric), [filterPreview, metric])
    const renderInfo = useMemo<LogsFilterVolumeSparklineRenderInfo>(
        () => ({
            ...seriesData,
            points: filterPreview,
            truncated: (filterPreview?.length ?? 0) >= SPARKLINE_ROW_LIMIT,
        }),
        [seriesData, filterPreview]
    )

    const formattedTotal =
        metric === 'bytes' ? formatBytes(seriesData.total) : `${seriesData.total.toLocaleString()} logs`
    const goalLines = buildGoalLines?.(renderInfo)
    const caption = filterPreview && !filterPreviewLoading ? renderCaption?.(renderInfo) : null

    // A bar fill is painted on canvas, which can't resolve a CSS variable.
    const series = useMemo<Series[]>(
        () => seriesData.series.map((s) => (s.color ? { ...s, color: resolveVariableColor(s.color) } : s)),
        [seriesData.series]
    )
    const formatValue = metric === 'bytes' ? formatBytes : humanFriendlyNumber
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            // Bucket timestamps carry an offset, and the settings pages around this preview read in
            // the viewer's own time.
            xAxis: { timezone: dayjs.tz.guess(), interval: bucketInterval(seriesData.bucketSeconds) },
            // Value ticks would only cost plot height here, because the header prints the total, a
            // goal line carries its own value, and the tooltip gives exact per-service numbers.
            // Hiding is label-only, so a goal line above the peak still stretches the domain.
            yAxis: { hide: true, showGrid: false },
            // Drawn by default on both edges, but the left one would frame an axis nothing labels.
            showAxisLines: { y: false },
            goalLines,
            barCornerRadius: 2,
            showCrosshair: false,
            // Up to 11 rows (top services plus "Others") overflow the tooltip's max height, so it
            // has to be pinnable for the pointer to reach it and scroll. `valueFormatter` is
            // wrapped because both formatters take a second optional argument that quill would
            // fill with the hovered entry.
            tooltip: { pinnable: true, valueFormatter: (value: number) => formatValue(value), showTotal: true },
        }),
        // `buildGoalLines` hands back a fresh array every render, so the dep is its content — an
        // unrelated re-render of the form around us shouldn't rebuild the chart's config.
        [seriesData.bucketSeconds, JSON.stringify(goalLines ?? null), formatValue]
    )

    return (
        <div className="mt-3 flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs text-muted">
                <span>
                    Volume preview by service (last {lookback}, top {TOP_SERVICES_LIMIT}
                    {metric === 'bytes' ? ', bytes' : ''})
                </span>
                {hasFilters && !filterPreviewLoading ? <span>{formattedTotal}</span> : null}
            </div>
            {/* Quill charts fill a *flex* parent (their root is flex-1), so the sized box is a flex column. */}
            <div className="relative h-32 flex flex-col border border-border rounded-md bg-bg-light px-2 py-1">
                {!hasFilters ? (
                    <div className="h-full flex items-center justify-center text-muted text-xs">
                        Add a filter above to preview matching log volume
                    </div>
                ) : filterPreviewLoading ? (
                    <LemonSkeleton className="w-full h-full" />
                ) : !filterPreview ? (
                    <div className="h-full flex flex-col gap-1 items-center justify-center text-muted text-xs">
                        <span>Couldn't load the volume preview.</span>
                        <LemonButton size="xsmall" type="secondary" onClick={refreshFilterPreview}>
                            Retry
                        </LemonButton>
                    </div>
                ) : series.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-muted text-xs">
                        No logs match these filters in the last {lookback}
                    </div>
                ) : (
                    <TimeSeriesBarChart
                        series={series}
                        labels={seriesData.labels}
                        theme={theme}
                        config={config}
                        dataAttr="logs-filter-volume-preview"
                    />
                )}
            </div>
            {caption}
        </div>
    )
}
