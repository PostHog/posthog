import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'
import type { BarChartConfig, PointClickData, Series } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { BREAKDOWN_OTHER_DISPLAY, isNullBreakdown, BREAKDOWN_NULL_DISPLAY } from 'scenes/insights/utils'

import { BreakdownSinglePropertyStat } from './miniBreakdownsLogic'

interface BreakdownsStackedBarProps {
    properties: BreakdownSinglePropertyStat[]
    totalCount: number
    propertyName: string
    propertyLabel?: string
    onValueClick?: (value: BreakdownSinglePropertyStat) => void
}

export function BreakdownsStackedBar({
    properties,
    totalCount,
    propertyName,
    propertyLabel = propertyName,
    onValueClick,
}: BreakdownsStackedBarProps): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series<BreakdownSinglePropertyStat>[]>(
        () =>
            properties.map((item, index) => ({
                key: `${propertyName}:${index}`,
                label: isNullBreakdown(item.label) ? BREAKDOWN_NULL_DISPLAY : item.label,
                data: [item.count],
                meta: item,
            })),
        [properties, propertyName]
    )
    const labels = useMemo(() => [propertyLabel], [propertyLabel])
    const config = useChartConfig<BarChartConfig>(
        () => ({
            axisOrientation: 'horizontal',
            barLayout: 'percent',
            hideXAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: false,
            maxCategoryLabelWidth: 0,
            xTickFormatter: () => '',
            margins: { top: 0, right: 0, bottom: 0, left: 0 },
            barCornerRadius: 2,
            bars: {
                bandPadding: 0,
                fitToHeight: true,
                minBandSize: 8,
                roundStackEnds: true,
                shadow: false,
            },
            tooltip: {
                placement: 'cursor',
                pinnable: false,
                sortedByValue: true,
                valueFormatter: (_value, entry) => {
                    const count = (entry.series.meta as BreakdownSinglePropertyStat | undefined)?.count ?? 0
                    const percentage = totalCount > 0 ? (count / totalCount) * 100 : 0
                    return `${humanFriendlyLargeNumber(count)} occurrences (${percentage.toFixed(1)}%)`
                },
            },
        }),
        [totalCount]
    )

    const handlePointClick = ({ series: clickedSeries }: PointClickData<BreakdownSinglePropertyStat>): void => {
        const value = clickedSeries.meta
        if (value && value.label !== BREAKDOWN_OTHER_DISPLAY) {
            onValueClick?.(value)
        }
    }

    return (
        <div className="flex h-3 w-full overflow-hidden rounded-sm">
            <BarChart
                series={series}
                labels={labels}
                config={config}
                theme={theme}
                className="h-full"
                onPointClick={onValueClick ? handlePointClick : undefined}
            />
        </div>
    )
}
