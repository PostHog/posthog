import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconInfo } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { tracingDataLogic } from './tracingDataLogic'
import { tracingFiltersLogic } from './tracingFiltersLogic'
import type { TracingChartMode, TracingHeatmapYScale } from './tracingFiltersLogic'
import { TracingLatencyHeatmap } from './TracingLatencyHeatmap'
import { TracingSparkline } from './TracingSparkline'

const HEATMAP_Y_TOOLTIP =
    'Rows are duration buckets (each step is ~2× wall time). Linear lists buckets in order so slower spans sit toward the top. Log flips row order (default) — handy when you want tail latencies along the bottom edge.'

interface TracingChartPanelProps {
    displayTimezone: string
}

export function TracingChartPanel({ displayTimezone }: TracingChartPanelProps): JSX.Element {
    const [collapsed, setCollapsed] = useState(false)

    const { filters, utcDateRange } = useValues(tracingFiltersLogic)
    const { setChartMode, setHeatmapYScale, setDateRange } = useActions(tracingFiltersLogic)
    const { sparklineData, sparklineLoading, latencyHeatmapRows } = useValues(tracingDataLogic)

    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-bg-light px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                    onClick={() => setCollapsed(!collapsed)}
                    aria-expanded={!collapsed}
                    aria-controls="tracing-chart-panel"
                >
                    <span className="text-sm font-medium">Chart</span>
                </LemonButton>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={filters.chartMode}
                        options={[
                            { value: 'volume' satisfies TracingChartMode, label: 'Volume' },
                            { value: 'latency' satisfies TracingChartMode, label: 'Latency' },
                        ]}
                        onChange={(v) => setChartMode(v as TracingChartMode)}
                    />
                    {filters.chartMode === 'latency' ? (
                        <div className="flex items-center gap-1">
                            <span className="text-xs text-muted whitespace-nowrap">Duration axis</span>
                            <LemonSegmentedButton
                                size="xsmall"
                                value={filters.heatmapYScale}
                                options={[
                                    {
                                        value: 'log' satisfies TracingHeatmapYScale,
                                        label: 'Slow at bottom',
                                    },
                                    {
                                        value: 'linear' satisfies TracingHeatmapYScale,
                                        label: 'Slow at top',
                                    },
                                ]}
                                onChange={(v) => setHeatmapYScale(v as TracingHeatmapYScale)}
                            />
                            <Tooltip title={HEATMAP_Y_TOOLTIP}>
                                <IconInfo className="text-muted cursor-help shrink-0" />
                            </Tooltip>
                        </div>
                    ) : null}
                </div>
            </div>
            {!collapsed && (
                <div id="tracing-chart-panel" className="min-w-0">
                    {filters.chartMode === 'volume' ? (
                        <TracingSparkline
                            sparklineData={sparklineData}
                            sparklineLoading={sparklineLoading}
                            onDateRangeChange={setDateRange}
                            displayTimezone={displayTimezone}
                        />
                    ) : (
                        <TracingLatencyHeatmap
                            rows={latencyHeatmapRows}
                            loading={sparklineLoading}
                            yScaleMode={filters.heatmapYScale}
                            utcDateRange={utcDateRange}
                            displayTimezone={displayTimezone}
                        />
                    )}
                </div>
            )}
        </div>
    )
}
