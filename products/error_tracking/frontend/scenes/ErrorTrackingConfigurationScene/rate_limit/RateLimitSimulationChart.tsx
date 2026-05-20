import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

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

function fillBuckets(volume: ExceptionVolumeBucket[], bucketMinutes: number): ExceptionVolumeBucket[] {
    const option = getBucketOption(bucketMinutes)
    const bucketMs = option.minutes * 60_000
    const counts = new Map<number, number>()
    volume.forEach((b) => {
        const aligned = Math.floor(dayjs(b.bucket).valueOf() / bucketMs) * bucketMs
        counts.set(aligned, b.count)
    })
    const endMs = Math.floor(Date.now() / bucketMs) * bucketMs
    const buckets: ExceptionVolumeBucket[] = []
    for (let i = option.bucketCount - 1; i >= 0; i--) {
        const ms = endMs - i * bucketMs
        buckets.push({ bucket: dayjs(ms).toISOString(), count: counts.get(ms) ?? 0 })
    }
    return buckets
}

function formatBucketLabel(iso: string, bucketMinutes: number): string {
    const ts = dayjs(iso)
    if (bucketMinutes >= 1440) {
        return ts.format('MMM D')
    }
    return ts.format('MMM D, HH:mm')
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

    const { xData, yData } = useMemo(() => {
        const filled = fillBuckets(volume, bucketMinutes)
        const labels = filled.map((b) => formatBucketLabel(b.bucket, bucketMinutes))
        const counts = filled.map((b) => b.count)
        const xAxis = {
            column: {
                name: 'bucket',
                type: { name: 'STRING' as const, isNumerical: false },
                label: 'Bucket',
                dataIndex: 0,
            },
            data: labels,
        }

        if (!hasLimit || rateLimit === null) {
            return {
                xData: xAxis,
                yData: [
                    {
                        column: {
                            name: 'count',
                            type: { name: 'INTEGER' as const, isNumerical: true },
                            label: 'Exceptions',
                            dataIndex: 0,
                        },
                        data: counts,
                        settings: { display: { displayType: 'bar' as const } },
                    },
                ],
            }
        }

        const within = counts.map((c) => Math.min(c, rateLimit))
        const above = counts.map((c) => Math.max(c - rateLimit, 0))
        return {
            xData: xAxis,
            yData: [
                {
                    column: {
                        name: 'within',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Within limit',
                        dataIndex: 0,
                    },
                    data: within,
                    settings: { display: { displayType: 'bar' as const } },
                },
                {
                    column: {
                        name: 'above',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Would be dropped',
                        dataIndex: 0,
                    },
                    data: above,
                    settings: { display: { displayType: 'bar' as const, color: getColorVar('danger') } },
                },
            ],
        }
    }, [volume, bucketMinutes, hasLimit, rateLimit])

    const goalLines = useMemo(() => {
        if (!hasLimit || rateLimit === null) {
            return []
        }
        const option = getBucketOption(bucketMinutes)
        return [
            {
                label: `Limit: ${rateLimit} per ${option.label}`,
                value: rateLimit,
                displayLabel: true,
            },
        ]
    }, [hasLimit, rateLimit, bucketMinutes])

    return (
        <div className="h-80 border rounded">
            <LineGraph
                className="h-full p-4"
                xData={xData}
                yData={yData}
                visualizationType={hasLimit ? ChartDisplayType.ActionsStackedBar : ChartDisplayType.ActionsBar}
                chartSettings={{ showXAxisTicks: false, showXAxisBorder: false }}
                goalLines={goalLines}
            />
        </div>
    )
}
