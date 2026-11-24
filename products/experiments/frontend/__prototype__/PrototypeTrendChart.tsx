/** Scratch prototype: inline delta-over-time chart for v2. Not committed. */
import { useMemo } from 'react'

import { LineChart, type LineChartConfig, ReferenceLine, type Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { EXPOSURES } from './prototypeData'
import type { VariantTrend } from './prototypeTimeseries'

function formatPercent(value: number): string {
    return `${value > 0 ? '+' : ''}${Math.round(value * 100)}%`
}

export function PrototypeTrendChart({
    trends,
    colors,
    limit,
    height,
    showValueAxis,
}: {
    trends: VariantTrend[]
    colors: Record<string, string>
    limit: number
    height: number
    showValueAxis: 'yes' | 'no'
}): JSX.Element {
    const theme = useChartTheme()
    const series: Series[] = useMemo(
        () =>
            trends.flatMap((trend) => [
                {
                    key: `${trend.key}-band`,
                    label: `${trend.key} interval`,
                    data: trend.upper,
                    color: colors[trend.key],
                    stroke: { width: 0 },
                    fill: { opacity: trends.length > 1 ? 0.12 : 0.2, lowerData: trend.lower },
                    visibility: { tooltip: false },
                },
                {
                    key: trend.key,
                    label: trend.key,
                    data: trend.delta,
                    color: colors[trend.key],
                    stroke: { width: 1.5 },
                },
            ]),
        [trends, colors]
    )
    const config: LineChartConfig = useMemo(
        () => ({
            hideXAxis: true,
            hideYAxis: showValueAxis === 'no',
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            curve: 'monotone',
            valueDomain: { min: -limit, max: limit },
            yTickFormatter: formatPercent,
            margins: { top: 4, right: 4, bottom: 4, left: showValueAxis === 'no' ? 0 : 36 },
            tooltip: { enabled: false },
        }),
        [limit, showValueAxis]
    )
    return (
        <div className="relative flex flex-col" style={{ height }}>
            <LineChart series={series} labels={EXPOSURES.days} theme={theme} config={config}>
                <ReferenceLine value={0} orientation="horizontal" variant="marker" showValueOnHover={false} />
            </LineChart>
        </div>
    )
}
