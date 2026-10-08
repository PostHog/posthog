import { useMemo } from 'react'

import { type ChartTheme, type TooltipContext } from '@posthog/quill-charts'
import { Skeleton } from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { Card, CardState } from '../dashboard/Card'
import { ChartTooltip } from '../dashboard/ChartTooltip'
import { formatNumber } from '../dashboard/formatters'
import { ShareBarChart, type ShareBarRow } from '../dashboard/ShareBarChart'
import { hasKnownLabels, topFacetRows, type WindowFacetRow } from './leaderboardShares'

const MAX_ROWS = 8

function renderTooltip(ctx: TooltipContext<WindowFacetRow & { share: number }>): JSX.Element | null {
    const row = ctx.seriesData[0]?.series.meta
    if (!row) {
        return null
    }
    return (
        <ChartTooltip
            title={row.label}
            rows={[
                ['Calls', formatNumber(row.calls)],
                ['Share', formatPercentage(row.share, { compact: true })],
                ['Users', formatNumber(row.users)],
            ]}
        />
    )
}

// Renders nothing once loaded when no row names a value: a property the server never sends would
// otherwise show a single "Unknown" bar.
export function FacetShareCard({
    title,
    rows,
    loading,
    theme,
}: {
    title: string
    rows: WindowFacetRow[]
    loading: boolean
    theme: ChartTheme
}): JSX.Element | null {
    const shownRows = useMemo(() => topFacetRows(rows, MAX_ROWS), [rows])
    const totalCalls = useMemo(() => shownRows.reduce((sum, row) => sum + row.calls, 0), [shownRows])
    const chartRows = useMemo<ShareBarRow<WindowFacetRow>[]>(
        () =>
            shownRows.map((row, index) => ({
                key: row.label,
                label: row.label,
                value: row.calls,
                color:
                    row.label === 'Unknown' || row.label === 'Other'
                        ? theme.axisColor
                        : theme.colors[index % theme.colors.length],
                meta: row,
            })),
        [shownRows, theme]
    )

    if (!loading && !hasKnownLabels(rows)) {
        return null
    }
    return (
        <Card title={title} className="min-w-0">
            <CardState
                loading={loading}
                isEmpty={rows.length === 0}
                skeleton={<Skeleton className="h-48 w-full" />}
                empty={<div className="py-6 text-center text-[12px] text-secondary">No data in this date range.</div>}
            >
                <ShareBarChart
                    rows={chartRows}
                    totalCalls={totalCalls}
                    theme={theme}
                    tooltip={renderTooltip}
                    label={title}
                    fitContent
                />
            </CardState>
        </Card>
    )
}
