import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { getBucketOption, RateLimitHistoryBucket } from './rateLimitConfigLogic'
import { formatBucketLabel, getBucketTimeline } from './RateLimitSimulationChart'

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
    const { xData, yData, isEmpty } = useMemo(() => {
        const filled = fillHistoryBuckets(history, bucketMinutes)
        const labels = filled.map((b) => formatBucketLabel(b.bucket, bucketMinutes))
        const recorded = filled.map((b) => b.recorded)
        const dropped = filled.map((b) => b.dropped)
        const bypassed = filled.map((b) => b.bypassed)

        return {
            isEmpty: recorded.every((c) => c === 0) && dropped.every((c) => c === 0) && bypassed.every((c) => c === 0),
            xData: {
                column: {
                    name: 'bucket',
                    type: { name: 'STRING' as const, isNumerical: false },
                    label: 'Bucket',
                    dataIndex: 0,
                },
                data: labels,
            },
            yData: [
                {
                    column: {
                        name: 'recorded',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Recorded',
                        dataIndex: 0,
                    },
                    data: recorded,
                    settings: { display: { displayType: 'bar' as const } },
                },
                {
                    column: {
                        name: 'dropped',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Dropped',
                        dataIndex: 0,
                    },
                    data: dropped,
                    settings: { display: { displayType: 'bar' as const, color: getColorVar('danger') } },
                },
                {
                    column: {
                        name: 'bypassed',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Bypassed',
                        dataIndex: 0,
                    },
                    data: bypassed,
                    settings: { display: { displayType: 'bar' as const, color: getColorVar('warning') } },
                },
            ],
        }
    }, [history, bucketMinutes])

    if (isEmpty) {
        return (
            <div className="h-80 border rounded flex items-center justify-center text-muted-foreground text-sm p-4 text-center">
                {emptyMessage}
            </div>
        )
    }

    return (
        <div className="h-80 border rounded">
            <LineGraph
                className="h-full p-4"
                xData={xData}
                yData={yData}
                visualizationType={ChartDisplayType.ActionsStackedBar}
                chartSettings={{ showXAxisTicks: false, showXAxisBorder: false }}
            />
        </div>
    )
}
