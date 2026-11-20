import { type ValueDomain } from '@posthog/quill-charts'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { formatMs, formatMsAsSeconds } from './formatters'
import { RankedToolBarChart, type RankedToolBarChartProps } from './RankedToolBarChart'

const p95 = (row: ToolRow): number => row.p95_duration_ms

// Headroom past the slowest tool, which the axis then rounds up, so that tool's value label fits.
const latencyDomain = (maxMs: number): ValueDomain => ({ min: 0, include: [maxMs * 1.2] })

const latencyTooltipRows = (row: ToolRow): [string, string][] => [
    ['p95', formatMs(row.p95_duration_ms)],
    ['Calls', String(row.total_calls)],
]

export function ToolLatencyChart({ theme, ...props }: Omit<RankedToolBarChartProps, 'title'>): JSX.Element {
    return (
        <RankedToolBarChart
            {...props}
            theme={theme}
            title="Slowest tools by p95 latency"
            metric={{
                label: 'p95',
                // Matches the p95 line of the leaderboard's Latency chart, which takes palette slot 1.
                color: theme.colors[1],
                value: p95,
                formatValue: formatMsAsSeconds,
                valueDomain: latencyDomain,
                tooltipRows: latencyTooltipRows,
            }}
        />
    )
}
