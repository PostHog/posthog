import { useMemo, useState } from 'react'

import { type ChartTheme, type TooltipContext } from '@posthog/quill-charts'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'

import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import { Card, CardState } from './Card'
import { ChartTooltip } from './ChartTooltip'
import { formatNumber } from './formatters'
import { HarnessLogo } from './harness'
import { harnessChartLabel, summarizeHarnessBreakdown, type HarnessChartRow } from './harnessBreakdown'
import { HarnessBreakdownTable } from './HarnessBreakdownTable'
import { harnessColor } from './harnessRegistry'
import { ShareBarChart, type ShareBarRow } from './ShareBarChart'

function renderTooltip(ctx: TooltipContext<HarnessChartRow & { share: number }>): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const row = entry?.series.meta
    if (!row) {
        return null
    }
    return (
        <ChartTooltip
            title={harnessChartLabel(row.category)}
            rows={[
                ['Calls', formatNumber(row.total_calls)],
                ['Share of all calls', formatPercentage(row.share, { compact: true })],
                ...(row.sessions !== null ? [['Sessions', formatNumber(row.sessions)] as [string, string]] : []),
                ['Error rate', formatPercentage(row.error_rate_pct, { compact: true })],
            ]}
        />
    )
}

export function HarnessBarChart({
    rows,
    loading,
    theme,
    fillHeight = false,
}: {
    rows: HarnessRow[]
    loading: boolean
    theme: ChartTheme
    fillHeight?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const { totalCalls, chartRows: sortedRows, allRows } = useMemo(() => summarizeHarnessBreakdown(rows), [rows])
    const otherCalls = sortedRows.find((row) => row.category === 'Other')?.total_calls ?? 0
    const chartRows = useMemo<ShareBarRow<HarnessChartRow>[]>(
        () =>
            sortedRows.map((row) => ({
                key: row.category,
                label: harnessChartLabel(row.category),
                value: row.total_calls,
                color: harnessColor(theme, row.category),
                icon: <HarnessLogo category={row.category} />,
                meta: row,
            })),
        [sortedRows, theme]
    )

    return (
        <Card
            className="min-w-0 flex-1"
            title="Share of calls by harness"
            action={
                rows.length > 0 && (
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        data-attr="mcp-dashboard-show-all-harnesses"
                        onClick={() => setExpanded(true)}
                    >
                        Show all harnesses
                    </LemonButton>
                )
            }
        >
            <CardState
                loading={loading}
                isEmpty={rows.length === 0}
                skeleton={
                    <div className="h-80 space-y-6 py-3">
                        {Array.from({ length: 6 }).map((_, index) => (
                            <LemonSkeleton key={index} className="h-4 w-full" />
                        ))}
                    </div>
                }
                empty={
                    <div className="flex h-80 items-center justify-center text-xs text-secondary">
                        No harness data yet.
                    </div>
                }
            >
                <div
                    className="flex flex-wrap justify-between gap-2 text-xs text-secondary tabular-nums"
                    translate="no"
                >
                    <span>
                        {formatNumber(totalCalls)} {totalCalls === 1 ? 'call' : 'calls'}
                    </span>
                    {sortedRows.some((row) => row.category === 'Other') && (
                        <Tooltip title="Other harnesses includes clients outside the top six and clients that could not be classified. These calls are included in every share percentage.">
                            <span tabIndex={0} className="cursor-help decoration-dotted underline underline-offset-2">
                                {formatPercentage(totalCalls > 0 ? (otherCalls / totalCalls) * 100 : 0, {
                                    compact: true,
                                })}{' '}
                                other harnesses
                            </span>
                        </Tooltip>
                    )}
                </div>
                <ShareBarChart
                    rows={chartRows}
                    totalCalls={totalCalls}
                    theme={theme}
                    tooltip={renderTooltip}
                    fillHeight={fillHeight}
                    label="Calls by harness"
                />
            </CardState>
            <LemonModal title="All harnesses" isOpen={expanded} onClose={() => setExpanded(false)} width={640}>
                <HarnessBreakdownTable rows={allRows} totalCalls={totalCalls} />
            </LemonModal>
        </Card>
    )
}
