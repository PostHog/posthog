import { Badge, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type ToolRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartSkeleton } from './ChartSkeleton'
import { DESTRUCTIVE_ERROR_RATE_PCT, formatMs, formatNumber } from './formatters'

export type ToolRankingMetric = 'errorRate' | 'p95'

const METRIC_HEADERS: Record<ToolRankingMetric, string> = { errorRate: 'Error rate', p95: 'p95' }

function MetricCell({ row, metric }: { row: ToolRow; metric: ToolRankingMetric }): JSX.Element {
    if (metric === 'p95') {
        return <span className="tabular-nums">{formatMs(row.p95_duration_ms)}</span>
    }
    return (
        <Badge variant={row.error_rate_pct >= DESTRUCTIVE_ERROR_RATE_PCT ? 'destructive' : 'warning'}>
            {formatPercentage(row.error_rate_pct, { compact: true })}
        </Badge>
    )
}

export function ToolRankingCard({
    title,
    rows,
    metric,
    loading,
    failed,
    onRetry,
    emptyMessage,
    onSelect,
    dataAttr,
}: {
    title: string
    /** Already ranked, worst first. */
    rows: ToolRow[]
    metric: ToolRankingMetric
    loading: boolean
    failed: boolean
    onRetry: () => void
    emptyMessage?: string
    onSelect: (tool: string, tools: string[]) => void
    dataAttr: string
}): JSX.Element {
    const tools = rows.map((row) => row.tool)
    return (
        <Card title={title} className="min-w-0" flush>
            <CardState
                loading={loading}
                isEmpty={rows.length === 0}
                failed={failed}
                onRetry={onRetry}
                className="min-h-48"
                skeleton={<ChartSkeleton kind="bars" />}
                empty={
                    <div className="flex flex-1 items-center justify-center px-4 text-center text-xs text-secondary">
                        {emptyMessage ?? 'No tool calls in this date range.'}
                    </div>
                }
            >
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Tool</TableHead>
                            <TableHead align="right">{METRIC_HEADERS[metric]}</TableHead>
                            <TableHead align="right">Calls</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {rows.map((row) => (
                            <TableRow
                                key={row.tool}
                                className="cursor-pointer"
                                onClick={() => onSelect(row.tool, tools)}
                                data-attr={dataAttr}
                            >
                                <TableCell expand>
                                    <button
                                        type="button"
                                        className="cursor-pointer truncate text-left font-mono text-sm"
                                    >
                                        {row.tool}
                                    </button>
                                </TableCell>
                                <TableCell align="right">
                                    <MetricCell row={row} metric={metric} />
                                </TableCell>
                                <TableCell align="right" className="tabular-nums">
                                    {formatNumber(row.total_calls)}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </CardState>
        </Card>
    )
}
