import { type ChartTheme } from '@posthog/quill-charts'
import {
    Metric,
    type MetricChange,
    MetricDelta,
    MetricHeader,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'
import { Card, CardContent, cn, Skeleton } from '@posthog/quill-primitives'

export interface MetricTileProps {
    label: string
    value: number
    formatValue: (n: number) => string
    theme: ChartTheme
    loading: boolean
    data?: number[]
    labels?: string[]
    color?: string
    goodDirection?: 'up' | 'down'
    /** Caption at rest ('Total' | 'Avg' | 'Last 7 days'); hovering a sparkline point swaps in its label. */
    restingSubtitle: string
    /** Resting comparison pill; pass `null` (or omit) to suppress. */
    change?: MetricChange | null
    changeTooltip?: string
    hoverChangeFromPreviousPoint?: boolean
    sparklineHeight?: number
    className?: string
}

/** The MCP analytics stat tile — Card + skeleton + composed Metric, shared by the dashboard
 *  KPI grid and the tool detail page. */
export function MetricTile({
    label,
    value,
    formatValue,
    theme,
    loading,
    data,
    labels,
    color,
    goodDirection,
    restingSubtitle,
    change = null,
    changeTooltip,
    hoverChangeFromPreviousPoint = false,
    sparklineHeight,
    className,
}: MetricTileProps): JSX.Element {
    const hasSparkline = data != null && data.length > 0
    return (
        <Card size="sm" flush={hasSparkline} className={cn('flex-1', className)}>
            {loading ? (
                <CardContent className="flex flex-col gap-2">
                    <Skeleton className="h-3 w-16" />
                    <Skeleton className="h-7 w-20" />
                </CardContent>
            ) : (
                <Metric
                    className="px-3 text-primary"
                    value={value}
                    data={hasSparkline ? data : undefined}
                    labels={hasSparkline ? labels : undefined}
                    theme={theme}
                    color={color}
                    goodDirection={goodDirection}
                    formatValue={formatValue}
                    change={change}
                    changeTooltip={changeTooltip}
                    hoverChangeFromPreviousPoint={hoverChangeFromPreviousPoint}
                    restingSubtitle={restingSubtitle}
                    sparklineHeight={sparklineHeight}
                >
                    <MetricHeader>
                        <MetricTitle>{label}</MetricTitle>
                        <MetricDelta />
                    </MetricHeader>
                    <MetricValue className="mt-2" />
                    <MetricSubtitle className="mt-1" />
                    <MetricSparkline className="mt-3 -mx-3" />
                </Metric>
            )}
        </Card>
    )
}
