import { useMemo } from 'react'

import { type Series, TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { getBucketOption, RateLimitHistoryBucket } from './rateLimitConfigLogic'
import { buildRateLimitBarChartConfig, formatBucketLabel, getBucketTimeline } from './RateLimitSimulationChart'

function fillHistoryBuckets(history: RateLimitHistoryBucket[], bucketMinutes: number): RateLimitHistoryBucket[] {
    const bucketMs = getBucketOption(bucketMinutes).minutes * 60_000
    const byBucket = new Map<number, RateLimitHistoryBucket>()
    history.forEach((b) => {
        const aligned = Math.floor(dayjs(b.bucket).valueOf() / bucketMs) * bucketMs
        byBucket.set(aligned, b)
    })
    return getBucketTimeline(bucketMinutes).map((ms) => {
        const entry = byBucket.get(ms)
        return {
            bucket: dayjs(ms).toISOString(),
            recorded: entry?.recorded ?? 0,
            dropped: entry?.dropped ?? 0,
            bypassed: entry?.bypassed ?? 0,
        }
    })
}

export function RateLimitHistoryChart({
    history,
    bucketMinutes,
    emptyMessage = 'No rate limiting activity recorded yet. Exceptions dropped by your project-wide limit will appear here.',
}: {
    history: RateLimitHistoryBucket[]
    bucketMinutes: number
    emptyMessage?: string
}): JSX.Element {
    const { labels, series, isEmpty } = useMemo(() => {
        const filled = fillHistoryBuckets(history, bucketMinutes)
        const recorded = filled.map((b) => b.recorded)
        const dropped = filled.map((b) => b.dropped)
        const bypassed = filled.map((b) => b.bypassed)

        return {
            isEmpty: recorded.every((c) => c === 0) && dropped.every((c) => c === 0) && bypassed.every((c) => c === 0),
            labels: filled.map((b) => formatBucketLabel(b.bucket, bucketMinutes)),
            series: [
                { key: 'recorded', label: 'Recorded', data: recorded },
                { key: 'dropped', label: 'Dropped', data: dropped, color: getColorVar('danger') },
                { key: 'bypassed', label: 'Bypassed', data: bypassed, color: getColorVar('warning') },
            ] as Series[],
        }
    }, [history, bucketMinutes])

    const theme = useChartTheme()
    const config = useChartConfig(() => buildRateLimitBarChartConfig('stacked'), [])

    if (isEmpty) {
        return (
            <div className="h-80 border rounded flex items-center justify-center text-muted-foreground text-sm p-4 text-center">
                {emptyMessage}
            </div>
        )
    }

    return (
        // Quill charts fill a *flex* parent (their root is flex-1), so the sized container must be a flex column.
        <div className="h-80 border rounded p-4 flex flex-col">
            <TimeSeriesBarChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}
