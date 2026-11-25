import { useMemo } from 'react'

import { DefaultTooltip, type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { LogsAlertSimulateBucketApi, LogsAlertSimulateResponseApi } from 'products/logs/frontend/generated/api.schemas'

function BucketTooltipDetails({ bucket }: { bucket: LogsAlertSimulateBucketApi | undefined }): JSX.Element | null {
    if (!bucket) {
        return null
    }
    const details = [`State: ${bucket.state}`]
    if (bucket.threshold_breached) {
        details.push('Threshold breached')
    }
    if (bucket.notification === 'fire') {
        details.push('Notification sent')
    } else if (bucket.notification === 'resolve') {
        details.push('Resolved notification sent')
    }
    return (
        <div className="flex flex-col text-left">
            {details.map((detail) => (
                <span key={detail}>{detail}</span>
            ))}
        </div>
    )
}

export function LogsAlertSimulationChart({ result }: { result: LogsAlertSimulateResponseApi }): JSX.Element {
    const { labels, series } = useMemo(
        () => ({
            labels: result.buckets.map((b: LogsAlertSimulateBucketApi) => b.timestamp),
            series: [
                {
                    key: 'count',
                    label: 'Log count',
                    data: result.buckets.map((b: LogsAlertSimulateBucketApi) => b.count),
                    // One series with per-bar colors, so a bucket's simulated outcome is visible without
                    // splitting the counts across three mutually exclusive series.
                    bars: result.buckets.map((b: LogsAlertSimulateBucketApi) => {
                        if (b.notification === 'fire') {
                            return { color: getColorVar('danger') }
                        }
                        return b.threshold_breached ? { color: getColorVar('warning') } : {}
                    }),
                },
            ] as Series[],
        }),
        [result]
    )

    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            showCrosshair: false,
            // Buckets are minutes apart, and the surrounding incident table renders in local time.
            xAxis: { interval: 'minute', timezone: dayjs.tz.guess() },
            goalLines: [
                {
                    value: result.threshold_count,
                    label: 'Threshold',
                    displayLabel: true,
                },
            ],
        }),
        [result.threshold_count]
    )

    return (
        // Quill charts fill a *flex* parent (their root is flex-1), so the sized container must be a flex column.
        <div className="h-56 flex flex-col">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={(ctx) => (
                    <DefaultTooltip
                        {...ctx}
                        labelFormatter={(label) => dayjs(label).format('MMM D, HH:mm')}
                        footer={<BucketTooltipDetails bucket={result.buckets[ctx.dataIndex]} />}
                    />
                )}
            />
        </div>
    )
}
