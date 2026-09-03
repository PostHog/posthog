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
import { Card, CardContent, cn, Skeleton } from '@posthog/quill-primitives'

import { IntervalType } from '~/types'

import { formatBucketLabel } from '../timeBuckets'

export interface MetricTileProps {
    label: string
    value: number
    formatValue: (n: number) => string
    theme: ChartTheme
    loading: boolean
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
    // A stable identity per interval, so `Metric`'s memoized context does not rebuild every render.
    const formatLabel = useMemo(() => (label: string) => formatBucketLabel(label, interval), [interval])
    return (
        <Card size="sm" flush={hasSparkline} className={cn('flex-1', className)}>
            {loading ? (
                <CardContent className="flex flex-col gap-2">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-7 w-20" />
                </CardContent>
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
                </Metric>
            )}
        </Card>
    )
}
