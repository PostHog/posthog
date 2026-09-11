import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { GenericMcpToolRenderer, ToolActivity } from 'products/posthog_ai/frontend/api/tools'
import type { ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { describeMetricsQuery, extractMetricSeries, MetricSeriesSummary } from './metricsQueryToolOutput'

// The thread stays scannable, so the body charts a bounded window of series and names the remainder.
const MAX_SERIES = 6

function formatTimestamp(timestamp: string): string {
    const parsed = dayjs(timestamp)
    return parsed.isValid() ? parsed.format('MMM D HH:mm') : timestamp
}

function SeriesRow({ series }: { series: MetricSeriesSummary }): JSX.Element {
    const latest = series.values.length > 0 ? series.values[series.values.length - 1] : null
    return (
        <div className="flex items-center gap-2">
            <div className="flex flex-col min-w-0 flex-1">
                <span className="text-xs font-mono truncate">{series.name}</span>
                {series.labels.length > 0 && (
                    <span className="text-muted text-xs font-mono truncate">{series.labels.join(' ')}</span>
                )}
            </div>
            <Sparkline
                data={series.values}
                labels={series.times.map(formatTimestamp)}
                type="line"
                // The chart carries no height of its own, so it needs one here or it draws nothing.
                className="h-8 shrink-0"
            />
            <span className="text-xs font-mono shrink-0 w-16 text-right">
                {latest === null ? '—' : humanFriendlyNumber(latest, 2)}
            </span>
        </div>
    )
}

function MetricSeriesBody({ series }: { series: MetricSeriesSummary[] }): JSX.Element {
    if (series.length === 0) {
        return <div className="text-muted">No series matched this query.</div>
    }

    const shown = series.slice(0, MAX_SERIES)
    return (
        <div className="flex flex-col gap-2">
            {shown.map((item, index) => (
                <SeriesRow key={index} series={item} />
            ))}
            {series.length > MAX_SERIES && (
                <div className="text-muted text-xs">+{series.length - MAX_SERIES} more not shown</div>
            )}
        </div>
    )
}

/**
 * Result card for the `query-metrics` tool: charts each returned series as a sparkline with its
 * latest value. The chart is the answer, so it renders always-visible rather than behind the
 * collapsed body. Falls back to the generic card for a pending call or an output with no `results`
 * array.
 */
export function MetricsQueryToolWidget(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const series = message.status === 'completed' ? extractMetricSeries(message) : null

    if (!series) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <ToolActivity
            message={message}
            icon={icon}
            title={displayName ?? 'Query metrics'}
            subtitle={describeMetricsQuery(message)}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        >
            <MetricSeriesBody series={series} />
        </ToolActivity>
    )
}
