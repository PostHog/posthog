import { useCallback, useMemo } from 'react'

import { ProportionBar } from '@posthog/quill-charts'
import type { ProportionBarConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

export interface Part {
    key: string
    label: string
    value: number
    color: string
}

// A part-to-whole bar. The legend is off because each signal names its parts in text next to the bar. Pass
// memoized parts, because the chart redraws when they change.
export function PartsBar({
    parts,
    unit,
    chartTooltip,
    height = 6,
}: {
    parts: Part[]
    // Names what a part's value counts, for the chart's hover details, for example "sessions".
    unit: string
    // Off where the signal already explains itself in its own tooltip, so that two tooltips do not open at once.
    chartTooltip: boolean
    height?: number
}): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () => parts.map((part) => ({ key: part.key, label: part.label, data: [part.value], color: part.color })),
        [parts]
    )
    const config = useMemo<ProportionBarConfig>(
        () => ({
            barHeight: height,
            barCornerRadius: Math.min(3, height / 2),
            legend: { show: false },
            tooltip: { enabled: chartTooltip },
        }),
        [height, chartTooltip]
    )
    const formatValue = useCallback(
        (value: number): string => `${humanFriendlyLargeNumber(Math.round(value))} ${unit}`,
        [unit]
    )
    return (
        <ProportionBar series={series} theme={theme} config={config} valueFormatter={formatValue} className="w-full" />
    )
}
