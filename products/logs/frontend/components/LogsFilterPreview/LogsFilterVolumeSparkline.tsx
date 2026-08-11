import { useActions, useValues } from 'kea'
import { useEffect, useId, useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Sparkline, SparklineReferenceLine } from 'lib/components/Sparkline'

import { UniversalFiltersGroup } from '~/types'

import {
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
    /** Overrides the auto-generated logic key; only needed by stories and tests. */
    previewKey?: string
    /** Threshold lines in the chart's own units, which depend on the resolved bucket width. */
    buildReferenceLines?: (info: LogsFilterVolumeSparklineRenderInfo) => SparklineReferenceLine[] | undefined
    /** Rendered under the chart once data has loaded (rate-limit note, retention projection). */
    renderCaption?: (info: LogsFilterVolumeSparklineRenderInfo) => JSX.Element | null
}

/**
 * Live preview of the log volume a filter group matches over the last 24h, broken down by service.
 * Shared by the drop-rule and retention-rule editors — one request serves both metrics, since each
 * row carries `count` and `bytes_uncompressed`.
 */
export function LogsFilterVolumeSparkline({
    filterGroup,
    metric,
    previewKey,
    buildReferenceLines,
    renderCaption,
}: LogsFilterVolumeSparklineProps): JSX.Element {
    const generatedKey = useId()
    const logic = logsFilterVolumePreviewLogic({ previewKey: previewKey ?? generatedKey })
    const { filterPreview, filterPreviewLoading } = useValues(logic)
    const { setPreviewRequest, refreshFilterPreview } = useActions(logic)

    const hasFilters = filterGroup.values.length > 0

    // Serialized so a re-render handing us a fresh-but-equal object doesn't re-fire the request.
    // Mounting runs this too, which covers the edit-mode case of opening a form with filters already set.
    // `metric` is a dependency because the backend ranks by it before collapsing the tail, so
    // switching metric needs a fresh request to get the right top-N back.
    const serializedFilterGroup = useMemo(() => JSON.stringify(filterGroup), [filterGroup])
    useEffect(() => {
        setPreviewRequest(filterGroup, metric)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [serializedFilterGroup, metric])

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
    const referenceLines = buildReferenceLines?.(renderInfo)
    const caption = filterPreview && !filterPreviewLoading ? renderCaption?.(renderInfo) : null

    return (
        <div className="mt-3 flex flex-col gap-1">
            <div className="flex items-center justify-between text-xs text-muted">
                <span>
                    Volume preview by service (last 24h, top {TOP_SERVICES_LIMIT}
                    {metric === 'bytes' ? ', bytes' : ''})
                </span>
                {hasFilters && !filterPreviewLoading ? <span>{formattedTotal}</span> : null}
            </div>
            <div className="relative h-24 border border-border rounded-md bg-bg-light px-2 py-1">
                {!hasFilters ? (
                    <div className="h-full flex items-center justify-center text-muted text-xs">
                        Add a filter above to preview matching log volume
                    </div>
                ) : filterPreviewLoading ? (
                    <Sparkline data={[]} labels={[]} loading className="w-full h-full" maximumIndicator={false} />
                ) : !filterPreview ? (
                    <div className="h-full flex flex-col gap-1 items-center justify-center text-muted text-xs">
                        <span>Couldn't load the volume preview.</span>
                        <LemonButton size="xsmall" type="secondary" onClick={refreshFilterPreview}>
                            Retry
                        </LemonButton>
                    </div>
                ) : seriesData.series.length === 0 ? (
                    <div className="h-full flex items-center justify-center text-muted text-xs">
                        No logs match these filters in the last 24h
                    </div>
                ) : (
                    <Sparkline
                        data={seriesData.series}
                        labels={seriesData.labels}
                        className="w-full h-full"
                        maximumIndicator={false}
                        referenceLines={referenceLines}
                        renderTooltipValue={metric === 'bytes' ? formatBytes : undefined}
                        // Up to 11 rows (top services plus "Others") overflows the tooltip's max
                        // height, so the pointer has to be able to reach it to scroll.
                        interactiveTooltip
                    />
                )}
            </div>
            {caption}
        </div>
    )
}
