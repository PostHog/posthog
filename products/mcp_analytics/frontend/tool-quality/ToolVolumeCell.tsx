import { useValues } from 'kea'
import { useMemo } from 'react'

import { TZLabel } from 'lib/components/TZLabel'
import type { SparklineData } from 'lib/components/VolumeSparkline/types'
import { VolumeSparkline } from 'lib/components/VolumeSparkline/VolumeSparkline'
import { volumeSparklineLogic } from 'lib/components/VolumeSparkline/volumeSparklineLogic'
import { dayjs } from 'lib/dayjs'
import { formatPercentage } from 'lib/utils/numbers'
import { formatBucketLabel, normalizeBucket } from 'lib/utils/timeBuckets'

import type { MCPToolQualityRowBucket } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { DESTRUCTIVE_ERROR_RATE_PCT, formatMs, formatNumber } from '../dashboard/formatters'

export type BucketIssue = 'errors' | 'slow' | null

// CSS variables, which the shared sparkline resolves for the canvas. They match the row's error rate and p95 badges.
export const ISSUE_COLORS: Record<Exclude<BucketIssue, null>, string> = {
    errors: 'var(--danger)',
    slow: 'var(--warning)',
}

/** Errors win over latency, so a bucket that is both reads as failing. */
export function bucketIssue(bucket: MCPToolQualityRowBucket, slowThresholdMs: number | null): BucketIssue {
    if (bucket.calls > 0 && (bucket.errors / bucket.calls) * 100 >= DESTRUCTIVE_ERROR_RATE_PCT) {
        return 'errors'
    }
    if (slowThresholdMs !== null && bucket.p95_duration_ms > slowThresholdMs) {
        return 'slow'
    }
    return null
}

export function ToolVolumeCell({
    tool,
    buckets,
    labels,
    interval,
    slowThresholdMs,
    lastSeen,
}: {
    tool: string
    buckets: MCPToolQualityRowBucket[]
    /** The window's bucket keys, so every row's bars line up. */
    labels: string[]
    interval: IntervalType
    slowThresholdMs: number | null
    lastSeen: string
}): JSX.Element {
    const sparklineKey = `mcp-tool-volume-${tool}`
    const byBucket = useMemo(
        () => new Map(buckets.map((bucket) => [normalizeBucket(bucket.bucket), bucket])),
        [buckets]
    )
    const data = useMemo<SparklineData>(
        () =>
            labels.map((label) => {
                const bucket = byBucket.get(label)
                const issue = bucket ? bucketIssue(bucket, slowThresholdMs) : null
                return {
                    date: dayjs(label).toDate(),
                    value: bucket?.calls ?? 0,
                    color: issue ? ISSUE_COLORS[issue] : undefined,
                }
            }),
        [labels, byBucket, slowThresholdMs]
    )
    // Like error tracking, the hovered bucket shows under the chart instead of in a tooltip.
    const { hoveredIndex, isBarHighlighted } = useValues(volumeSparklineLogic({ sparklineKey }))
    const hoveredLabel = isBarHighlighted && hoveredIndex !== null ? labels[hoveredIndex] : undefined
    const hovered = hoveredLabel ? byBucket.get(hoveredLabel) : undefined
    // The stat behind a colored bar is emphasized in the bar's color, so the hover says why.
    const hoveredIssue = hovered ? bucketIssue(hovered, slowThresholdMs) : null

    return (
        <div className="flex w-48 max-w-full min-w-0 flex-col">
            <div className="h-12 min-h-12 w-full">
                <VolumeSparkline
                    className="h-full"
                    data={data}
                    layout="compact"
                    xAxis="minimal"
                    sparklineKey={sparklineKey}
                    dataAttr="mcp-tool-volume-sparkline"
                />
            </div>
            <div className="flex h-4 w-full items-center justify-between gap-1 px-1 text-[10px] leading-none text-muted">
                {hoveredLabel ? (
                    <>
                        <span className="min-w-0 truncate">{formatBucketLabel(hoveredLabel, interval)}</span>
                        <span className="shrink-0 text-right tabular-nums" translate="no">
                            {hovered ? (
                                <>
                                    <span>{formatNumber(hovered.calls)} calls · </span>
                                    <span
                                        className={hoveredIssue === 'errors' ? 'font-semibold text-danger' : undefined}
                                    >
                                        {formatPercentage((hovered.errors / Math.max(hovered.calls, 1)) * 100, {
                                            compact: true,
                                        })}{' '}
                                        errors
                                    </span>
                                    <span> · </span>
                                    <span
                                        className={hoveredIssue === 'slow' ? 'font-semibold text-warning' : undefined}
                                    >
                                        {hovered.p95_duration_ms > 0 ? formatMs(hovered.p95_duration_ms) : '–'} p95
                                    </span>
                                </>
                            ) : (
                                '0 calls'
                            )}
                        </span>
                    </>
                ) : (
                    <span className="ml-auto whitespace-nowrap">
                        <TZLabel time={lastSeen} />
                    </span>
                )}
            </div>
        </div>
    )
}
