import { useMemo } from 'react'

import { type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { ExceptionVolumeBucket, getBucketOption } from './rateLimitConfigLogic'

export function formatTotalDuration(bucketMinutes: number): string {
    const option = getBucketOption(bucketMinutes)
    const totalMinutes = option.minutes * option.bucketCount
    if (totalMinutes >= 10080) {
        return pluralize(Math.round(totalMinutes / 10080), 'week')
    }
    if (totalMinutes >= 1440) {
        return pluralize(Math.round(totalMinutes / 1440), 'day')
    }
    return pluralize(Math.round(totalMinutes / 60), 'hour')
}

export function getBucketTimeline(bucketMinutes: number): number[] {
    const option = getBucketOption(bucketMinutes)
    const bucketMs = option.minutes * 60_000
    const endMs = Math.floor(Date.now() / bucketMs) * bucketMs
    const timeline: number[] = []
    for (let i = option.bucketCount - 1; i >= 0; i--) {
        timeline.push(endMs - i * bucketMs)
    }
    return timeline
}

function fillBuckets(volume: ExceptionVolumeBucket[], bucketMinutes: number): ExceptionVolumeBucket[] {
    const bucketMs = getBucketOption(bucketMinutes).minutes * 60_000
    const counts = new Map<number, number>()
    volume.forEach((b) => {
        const aligned = Math.floor(dayjs(b.bucket).valueOf() / bucketMs) * bucketMs
        counts.set(aligned, b.count)
    })
    return getBucketTimeline(bucketMinutes).map((ms) => ({
        bucket: dayjs(ms).toISOString(),
        count: counts.get(ms) ?? 0,
    }))
}

export function formatBucketLabel(iso: string, bucketMinutes: number): string {
    const ts = dayjs(iso)
    if (bucketMinutes >= 1440) {
        return ts.format('MMM D')
    }
    return ts.format('MMM D, HH:mm')
}

/** Shared config for the rate limit bar charts: hidden bucket ticks, stacked bars, default tooltip
 *  with a total row. */
export function buildRateLimitBarChartConfig(
    barLayout: NonNullable<TimeSeriesBarChartConfig['barLayout']>
): TimeSeriesBarChartConfig {
    return {
        xAxis: { hide: true },
        showAxisLines: { x: false, y: true },
        barLayout,
        legend: { show: false },
        tooltip: {
            placement: 'cursor',
            pinnable: true,
            sortedByValue: true,
            showTotal: true,
        },
    }
}

export function RateLimitSimulationChart({
    volume,
    rateLimit,
    bucketMinutes,
}: {
    volume: ExceptionVolumeBucket[]
    rateLimit: number | null
    bucketMinutes: number
}): JSX.Element {
    const hasLimit = !!rateLimit && rateLimit > 0

    const { labels, series } = useMemo(() => {
        const filled = fillBuckets(volume, bucketMinutes)
        const labels = filled.map((b) => formatBucketLabel(b.bucket, bucketMinutes))
        const counts = filled.map((b) => b.count)

        if (!hasLimit || rateLimit === null) {
            return {
                labels,
                series: [{ key: 'count', label: 'Exceptions', data: counts }] as Series[],
            }
        }

        return {
            labels,
            series: [
                { key: 'within', label: 'Within limit', data: counts.map((c) => Math.min(c, rateLimit)) },
                {
                    key: 'above',
                    label: 'Would be dropped',
                    data: counts.map((c) => Math.max(c - rateLimit, 0)),
                    color: getColorVar('danger'),
                },
            ] as Series[],
        }
    }, [volume, bucketMinutes, hasLimit, rateLimit])

    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesBarChartConfig>(() => {
        const base = buildRateLimitBarChartConfig(hasLimit ? 'stacked' : 'grouped')
        if (!hasLimit || rateLimit === null) {
            return base
        }
        const option = getBucketOption(bucketMinutes)
        return {
            ...base,
            goalLines: [
                {
                    label: `Limit: ${rateLimit} per ${option.label}`,
                    value: rateLimit,
                    displayLabel: true,
                },
            ],
        }
    }, [hasLimit, rateLimit, bucketMinutes])

    return (
        // Quill charts fill a *flex* parent (their root is flex-1), so the sized container must be a flex column.
        <div className="h-80 border rounded p-4 flex flex-col">
            <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
