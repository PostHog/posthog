import { type ValueDomain } from '@posthog/quill-charts'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { formatMs, formatMsAsSeconds } from './formatters'
import { RankedToolBarChart, type RankedToolBarChartProps } from './RankedToolBarChart'

// --color-amber-600 in sRGB. Amber is a warning hue beside the error card's red, and blue on this
// dashboard means call volume. The chart takes only hex or rgb series colors, and the token is oklch.
// This step is dark enough that the chart's contrast rule draws the value labels in white.
const SLOW_TOOL_AMBER = '#e17100'

const p95 = (row: ToolRow): number => row.p95_duration_ms

// Headroom past the slowest tool, which the axis then rounds up, so that tool's value label fits.
const latencyDomain = (maxMs: number): ValueDomain => ({ min: 0, include: [maxMs * 1.2] })

const latencyTooltipRows = (row: ToolRow): [string, string][] => [
    ['p95', formatMs(row.p95_duration_ms)],
    ['Calls', String(row.total_calls)],
]

export function ToolLatencyChart(props: Omit<RankedToolBarChartProps, 'title'>): JSX.Element {
    return (
        <RankedToolBarChart
            {...props}
            title="Slowest tools by p95 latency"
            metric={{
                label: 'p95',
                color: SLOW_TOOL_AMBER,
                value: p95,
                formatValue: formatMsAsSeconds,
                valueDomain: latencyDomain,
                tooltipRows: latencyTooltipRows,
            }}
        />
    )
}
