import { type ValueDomain } from '@posthog/quill-charts'

import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { RankedToolBarChart, type RankedToolBarChartProps } from './RankedToolBarChart'

const formatErrorRate = (value: number): string => formatPercentage(value, { compact: true })

// Upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a clean 10,
// so the track ends just past the data (a 30% max gives a 50% track) rather than an empty-looking 100%.
function errorRateDomain(maxRate: number): ValueDomain {
    return { min: 0, max: Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10)) }
}

const errorRate = (row: ToolRow): number => row.error_rate_pct

const errorRateTooltipRows = (row: ToolRow): [string, string][] => [
    ['Error rate', formatErrorRate(row.error_rate_pct)],
    ['Errors', String(row.errors)],
    ['Calls', String(row.total_calls)],
]

export function ToolErrorRateChart({
    title = 'Tools with the highest error rate',
    theme,
    ...props
}: Omit<RankedToolBarChartProps, 'title'> & { title?: string }): JSX.Element {
    return (
        <RankedToolBarChart
            {...props}
            title={title}
            theme={theme}
            metric={{
                label: 'Error rate',
                color: theme.colors[4],
                value: errorRate,
                formatValue: formatErrorRate,
                valueDomain: errorRateDomain,
                tooltipRows: errorRateTooltipRows,
            }}
        />
    )
}
