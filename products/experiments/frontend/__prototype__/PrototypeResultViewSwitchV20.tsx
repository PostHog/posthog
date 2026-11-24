/** Scratch prototype v20: the result view switch as two small icon groups, so it fits on the metrics heading. Not committed. */
import { IconGridMasonry, IconLineGraph, IconRetentionHeatmap, IconStickiness, IconTrends } from '@posthog/icons'
import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import type { ResultChart, ResultLayout } from './PrototypeMetricViewsV16'

const LAYOUT_OPTIONS: { value: ResultLayout; label: string; icon: JSX.Element }[] = [
    { value: 'per-metric', label: 'Chart per metric', icon: <IconGridMasonry /> },
    { value: 'all-metrics', label: 'One chart', icon: <IconLineGraph /> },
]

const CHART_OPTIONS: { value: ResultChart; label: string; icon: JSX.Element }[] = [
    { value: 'trend', label: 'Delta over time', icon: <IconTrends /> },
    { value: 'candlestick', label: 'Candlestick', icon: <IconStickiness /> },
    { value: 'matrix', label: 'Matrix', icon: <IconRetentionHeatmap /> },
]

/** The same two choices as v16, without labels or the hint line. Each icon names itself in a tooltip. */
export function CompactResultViewSwitch({
    layout,
    chart,
    onLayoutChange,
    onChartChange,
}: {
    layout: ResultLayout
    chart: ResultChart
    onLayoutChange: (layout: ResultLayout) => void
    onChartChange: (chart: ResultChart) => void
}): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-attr="result-view-switch">
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[layout]}
                onValueChange={(value: string[]) => value[0] && onLayoutChange(value[0] as ResultLayout)}
                aria-label="Chart layout"
                data-attr="result-layout"
            >
                {LAYOUT_OPTIONS.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        aria-label={option.label}
                        {...({ tooltip: option.label } as object)}
                    >
                        {option.icon}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <ToggleGroup
                variant="outline"
                size="sm"
                value={[chart]}
                onValueChange={(value: string[]) => value[0] && onChartChange(value[0] as ResultChart)}
                aria-label="Chart type"
                data-attr="result-chart"
            >
                {CHART_OPTIONS.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        aria-label={option.label}
                        {...({ tooltip: option.label } as object)}
                    >
                        {option.icon}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
