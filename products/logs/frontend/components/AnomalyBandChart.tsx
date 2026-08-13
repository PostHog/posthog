import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { LogsAnomalyScanBucketApi, LogsAnomalyVerdictEnumApi } from 'products/logs/frontend/generated/api.schemas'

export interface BandChartData {
    labels: string[]
    observed: number[]
    lower: (number | null)[]
    upper: (number | null)[]
    verdicts: (LogsAnomalyVerdictEnumApi | null)[]
}

// Band values stay null for unscored buckets so the chart shows a gap there.
// Coercing them to 0 would render every unscored region as a drop to zero.
export function buildBandChartData(buckets: LogsAnomalyScanBucketApi[]): BandChartData {
    const spansMultipleDays =
        buckets.length > 1 && !dayjs(buckets[0].time).isSame(dayjs(buckets[buckets.length - 1].time), 'day')
    const format = spansMultipleDays ? 'MMM D HH:mm' : 'HH:mm'
    return {
        labels: buckets.map((bucket) => dayjs(bucket.time).format(format)),
        observed: buckets.map((bucket) => bucket.observed),
        lower: buckets.map((bucket) => bucket.lower),
        upper: buckets.map((bucket) => bucket.upper),
        verdicts: buckets.map((bucket) => bucket.verdict),
    }
}

const VERDICT_POINT_COLOR: Record<LogsAnomalyVerdictEnumApi, string> = {
    spike: 'rgba(220, 38, 38, 0.92)',
    drop: 'rgba(234, 88, 12, 0.9)',
    silence: 'rgba(127, 29, 29, 1)',
}

export function AnomalyBandChart({ buckets }: { buckets: LogsAnomalyScanBucketApi[] }): JSX.Element {
    const data = buildBandChartData(buckets)

    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'line' as const,
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Upper band',
                        data: data.upper,
                        borderColor: 'rgba(59, 130, 246, 0.35)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: false,
                        spanGaps: false,
                    },
                    {
                        label: 'Lower band',
                        data: data.lower,
                        borderColor: 'rgba(59, 130, 246, 0.35)',
                        backgroundColor: 'rgba(59, 130, 246, 0.12)',
                        borderWidth: 1,
                        pointRadius: 0,
                        fill: '-1',
                        spanGaps: false,
                    },
                    {
                        label: 'Observed',
                        data: data.observed,
                        borderColor: 'rgba(30, 64, 175, 0.9)',
                        borderWidth: 1.5,
                        fill: false,
                        pointRadius: (context) => (data.verdicts[context.dataIndex] ? 4 : 0),
                        pointHoverRadius: (context) => (data.verdicts[context.dataIndex] ? 5 : 3),
                        pointBackgroundColor: (context) => {
                            const verdict = data.verdicts[context.dataIndex]
                            return verdict ? VERDICT_POINT_COLOR[verdict] : 'transparent'
                        },
                        pointBorderColor: (context) => {
                            const verdict = data.verdicts[context.dataIndex]
                            return verdict ? VERDICT_POINT_COLOR[verdict] : 'transparent'
                        },
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false as const,
                interaction: { mode: 'nearest' as const, axis: 'x' as const, intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: true,
                        filter: (item) => item.dataset.label === 'Observed',
                        callbacks: {
                            title: (items) => (items[0] ? String(items[0].label) : ''),
                            label: (context) => {
                                const bucket = buckets[context.dataIndex]
                                const verdict = data.verdicts[context.dataIndex]
                                const suffix = verdict ? ` (${verdict})` : ''
                                return `Observed: ${humanFriendlyNumber(bucket.observed)}${suffix}`
                            },
                            afterLabel: (context) => {
                                const bucket = buckets[context.dataIndex]
                                if (bucket.expected == null || bucket.lower == null || bucket.upper == null) {
                                    return 'Not scored'
                                }
                                return `Expected: ${humanFriendlyNumber(bucket.expected)} (band ${humanFriendlyNumber(
                                    bucket.lower
                                )} to ${humanFriendlyNumber(bucket.upper)})`
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        display: true,
                        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 9 } },
                        grid: { display: false },
                    },
                    y: {
                        display: true,
                        beginAtZero: true,
                        ticks: {
                            maxTicksLimit: 5,
                            font: { size: 10 },
                            callback: (value: string | number) => humanFriendlyNumber(Number(value)),
                        },
                        grid: { color: 'rgba(0, 0, 0, 0.06)' },
                    },
                },
            },
        }),
        deps: [buckets],
    })

    return (
        <div className="h-40 w-full">
            <canvas ref={canvasRef} />
        </div>
    )
}
