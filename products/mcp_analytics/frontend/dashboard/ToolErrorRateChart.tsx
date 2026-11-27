import { type ValueDomain } from '@posthog/quill-charts'
import { ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { formatNumber } from './formatters'
import { RankedToolBarChart, type RankedToolBarChartProps, type RankedToolMetric } from './RankedToolBarChart'

export type ErrorRanking = 'rate' | 'count'

const formatErrorRate = (value: number): string => formatPercentage(value, { compact: true })

// Upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a clean 10,
// so the track ends just past the data (a 30% max gives a 50% track) rather than an empty-looking 100%.
function errorRateDomain(maxRate: number): ValueDomain {
    return { min: 0, max: Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10)) }
}

// Headroom past the top tool, which the axis then rounds up, so its value label fits.
const errorCountDomain = (maxErrors: number): ValueDomain => ({ min: 0, include: [maxErrors * 1.2] })

const errorRate = (row: ToolRow): number => row.error_rate_pct
const errorCount = (row: ToolRow): number => row.errors

const errorRateTooltipRows = (row: ToolRow): [string, string][] => [
    ['Error rate', formatErrorRate(row.error_rate_pct)],
    ['Errors', String(row.errors)],
    ['Calls', String(row.total_calls)],
]

const TITLES: Record<ErrorRanking, string> = {
    rate: 'Tools with the highest error rate',
    count: 'Tools with the most errors',
}

export function ToolErrorRateChart({
    title,
    theme,
    by = 'rate',
    onByChange,
    dataAttr,
    ...props
}: Omit<RankedToolBarChartProps, 'title'> & {
    title?: string
    by?: ErrorRanking
    /** Adds a switch between ranking by error rate and by error count. */
    onByChange?: (by: ErrorRanking) => void
    dataAttr?: string
}): JSX.Element {
    const metric: RankedToolMetric = {
        label: by === 'rate' ? 'Error rate' : 'Errors',
        color: theme.colors[4],
        value: by === 'rate' ? errorRate : errorCount,
        formatValue: by === 'rate' ? formatErrorRate : formatNumber,
        valueDomain: by === 'rate' ? errorRateDomain : errorCountDomain,
        tooltipRows: errorRateTooltipRows,
    }
    return (
        <RankedToolBarChart
            {...props}
            title={title ?? TITLES[by]}
            theme={theme}
            action={
                onByChange ? (
                    <div className="flex items-center gap-2">
                        {props.action}
                        <ToggleGroup
                            className="-my-1"
                            value={[by]}
                            onValueChange={(next) => next[0] && onByChange(next[0] as ErrorRanking)}
                            aria-label="Rank tools by"
                        >
                            <ToggleGroupItem value="rate" size="sm" data-attr={`${dataAttr}-by-rate`}>
                                Error rate
                            </ToggleGroupItem>
                            <ToggleGroupItem value="count" size="sm" data-attr={`${dataAttr}-by-count`}>
                                Total errors
                            </ToggleGroupItem>
                        </ToggleGroup>
                    </div>
                ) : (
                    props.action
                )
            }
            metric={metric}
        />
    )
}
