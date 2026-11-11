import { useMemo } from 'react'

import { type ChartTheme } from '@posthog/quill-charts'
import {
    Metric,
    type MetricChange,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'
import { Card, cn, Skeleton } from '@posthog/quill-primitives'

import { formatBucketLabel } from 'lib/utils/timeBuckets'

import { IntervalType } from '~/types'

import { CardError } from './Card'
import { SKELETON_COLOR, SKELETON_TRACK_COLOR } from './ChartSkeleton'

export interface MetricTileProps {
    label: string
    value: number
    formatValue: (n: number) => string
    theme: ChartTheme
    loading: boolean
    failed?: boolean
    onRetry?: () => void
    data?: number[]
    // Raw bucket keys, which the sparkline uses as its x-scale keys, so they must be unique per
    // point. Pre-formatted text repeats (every hour of a day reads "Sep 2") and a repeat collapses
    // two points onto one position. The tile formats them for the caption itself.
    labels?: string[]
    // Grouping interval of the buckets, which decides whether a caption needs the bucket's time.
    interval: IntervalType
    color?: string
    goodDirection?: 'up' | 'down'
    restingSubtitle: string
    change?: MetricChange | null
    changeTooltip?: string
    hoverChangeFromPreviousPoint?: boolean
    sparklineHeight?: number
    // Dash the sparkline from this index on, for a trailing bucket that is still collecting.
    sparklineDashedFromIndex?: number
    className?: string
}

export function MetricTile({
    label,
    value,
    formatValue,
    theme,
    loading,
    failed = false,
    onRetry,
    data,
    labels,
    interval,
    color,
    goodDirection,
    restingSubtitle,
    change = null,
    changeTooltip,
    hoverChangeFromPreviousPoint = false,
    sparklineHeight,
    sparklineDashedFromIndex,
    className,
}: MetricTileProps): JSX.Element {
    const hasSparkline = data != null && data.length > 0
    const flush = sparklineHeight != null || (!loading && !failed && hasSparkline)
    // A stable identity per interval, so `Metric`'s memoized context does not rebuild every render.
    const formatLabel = useMemo(() => (label: string) => formatBucketLabel(label, interval), [interval])
    return (
        <Card size="sm" flush={flush} className={cn('flex-1', className)}>
            {failed ? (
                <div className="grid flex-1 px-3">
                    <div className="invisible col-start-1 row-start-1" aria-hidden>
                        <MetricTileSkeleton sparklineHeight={sparklineHeight} />
                    </div>
                    <div className="col-start-1 row-start-1 flex flex-col">
                        <div className="text-sm font-medium">{label}</div>
                        <div className="flex flex-1 items-center justify-center py-2">
                            <CardError onRetry={onRetry} />
                        </div>
                    </div>
                </div>
            ) : loading ? (
                <div className="px-3">
                    <MetricTileSkeleton sparklineHeight={sparklineHeight} />
                </div>
            ) : (
                <Metric
                    className="px-3 text-primary"
                    value={value}
                    data={hasSparkline ? data : undefined}
                    labels={hasSparkline ? labels : undefined}
                    formatLabel={formatLabel}
                    theme={theme}
                    color={color}
                    goodDirection={goodDirection}
                    formatValue={formatValue}
                    change={change}
                    changeTooltip={changeTooltip}
                    hoverChangeFromPreviousPoint={hoverChangeFromPreviousPoint}
                    restingSubtitle={restingSubtitle}
                    sparklineHeight={sparklineHeight}
                    sparklineDashedFromIndex={sparklineDashedFromIndex}
                >
                    <MetricHeader>
                        <MetricTitle>{label}</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline className="mt-3 -mx-3" />
                    {/* An empty range draws no sparkline; keep its space so the tile matches its placeholder. */}
                    {!hasSparkline && sparklineHeight != null ? (
                        <div aria-hidden className="mt-3" style={{ height: sparklineHeight }} />
                    ) : null}
                </Metric>
            )}
        </Card>
    )
}

const SPARKLINE_PATH = 'M0,72 C12,64 22,68 34,56 S56,50 66,44 S86,34 100,30'

// Mirrors the line boxes of the loaded tile's header, value, subtitle and sparkline, so the tile
// keeps its height when the data arrives.
function MetricTileSkeleton({ sparklineHeight }: { sparklineHeight?: number }): JSX.Element {
    return (
        <div className="flex flex-col">
            <div className="flex h-5 items-center">
                <Skeleton className="h-3 w-16" />
            </div>
            <div className="mt-2 flex h-10 items-center">
                <Skeleton className="h-7 w-24" />
            </div>
            <div className="mt-1 flex h-5 items-center">
                <Skeleton className="h-3 w-20" />
            </div>
            {sparklineHeight != null ? (
                <svg
                    className="-mx-3 mt-3 w-[calc(100%+1.5rem)] animate-pulse"
                    style={{ height: sparklineHeight }}
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    aria-hidden
                >
                    <path d={`${SPARKLINE_PATH} L100,100 L0,100 Z`} fill={SKELETON_TRACK_COLOR} />
                    <path
                        d={SPARKLINE_PATH}
                        fill="none"
                        stroke={SKELETON_COLOR}
                        strokeWidth={2}
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
            ) : null}
        </div>
    )
}
