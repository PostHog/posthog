import { useValues } from 'kea'
import { useState } from 'react'

import { Skeleton, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { formatPercentage } from 'lib/utils/numbers'

import { labMark, modelLab } from '../aiLabs'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLabel } from '../dashboard/HarnessLabel'
import { MetricTile } from '../dashboard/MetricTile'
import { deltaPct } from '../mcpDashboardOverviewLogic'
import { ResultTable, SectionHeader } from '../MCPToolReport'
import { SessionDrawer } from '../sessions/SessionDrawer'
import { ExampleCallRow } from '../tool-quality/ExampleCallRow'
import type { PersonTopDimension } from './peopleQueries'
import { type PersonRecentCall, personReportLogic } from './personReportLogic'

const TOP_TABS: { value: PersonTopDimension; label: string }[] = [
    { value: 'tools', label: 'Tools' },
    { value: 'harnesses', label: 'Harnesses' },
    { value: 'models', label: 'Models' },
]

const TOP_LABEL: Record<PersonTopDimension, { header: string; render: (label: string) => JSX.Element }> = {
    tools: { header: 'Tool', render: (label) => <span className="truncate font-mono">{label}</span> },
    harnesses: { header: 'Harness', render: (label) => <HarnessLabel category={label} /> },
    models: {
        header: 'Model',
        render: (label) =>
            label === 'Unknown' ? (
                <span className="text-muted">Unknown</span>
            ) : (
                <span className="flex items-center gap-1.5">
                    <BrandMark name={labMark(modelLab(label))} className="size-4 shrink-0" />
                    <span className="truncate">{label}</span>
                </span>
            ),
    },
}

/** One person's report, on its page and in the People drawer. Mount it under a `personReportLogic`. */
export function PersonReport(): JSX.Element {
    const {
        totals,
        totalsLoading,
        series,
        seriesLoading,
        interval,
        incompleteTail,
        topRows,
        topRowsLoading,
        recentCalls,
        recentCallsLoading,
    } = useValues(personReportLogic)
    const theme = useChartTheme()
    const [topTab, setTopTab] = useState<PersonTopDimension>('tools')
    const [openedCall, setOpenedCall] = useState<PersonRecentCall | null>(null)

    const current = totals?.current
    const previous = totals?.previous
    const errorRate = (t: typeof current): number => (t && t.calls ? (t.errors / t.calls) * 100 : 0)
    const dashedFromIndex = incompleteTail && series && series.labels.length >= 2 ? series.labels.length - 1 : undefined
    const tiles = [
        {
            label: 'Calls',
            value: current?.calls ?? 0,
            before: previous?.calls,
            data: series?.calls,
            format: formatNumber,
            good: 'up' as const,
        },
        {
            label: 'Sessions',
            value: current?.sessions ?? 0,
            before: previous?.sessions,
            data: series?.sessions,
            format: formatNumber,
            good: 'up' as const,
        },
        {
            label: 'Error rate',
            value: errorRate(current),
            before: previous?.calls ? errorRate(previous) : undefined,
            data: series?.errorRatePct,
            format: (n: number) => formatPercentage(n, { compact: true }),
            good: 'down' as const,
        },
        {
            label: 'p95 latency',
            value: current?.p95Ms ?? 0,
            before: previous?.p95Ms,
            data: series?.p95Ms,
            format: formatMs,
            good: 'down' as const,
        },
    ]

    return (
        <div className="flex flex-col gap-6">
            <div className="@container">
                <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                    {tiles.map((tile) => {
                        const change = tile.before != null ? deltaPct(tile.value, tile.before) : null
                        return (
                            <MetricTile
                                key={tile.label}
                                label={tile.label}
                                loading={(totalsLoading && !totals) || (seriesLoading && !series)}
                                value={tile.value}
                                data={tile.data}
                                labels={series?.labels}
                                interval={interval}
                                theme={theme}
                                color={tile.label === 'Error rate' ? theme.colors[4] : theme.colors[0]}
                                goodDirection={tile.good}
                                formatValue={tile.format}
                                change={change !== null ? { value: change } : null}
                                changeTooltip={
                                    change !== null && tile.before != null
                                        ? `vs. ${tile.format(tile.before)} in the previous period`
                                        : undefined
                                }
                                hoverChangeFromPreviousPoint
                                restingSubtitle="Total"
                                sparklineHeight={50}
                                sparklineDashedFromIndex={dashedFromIndex}
                            />
                        )
                    })}
                </div>
            </div>

            <div className="flex flex-col gap-3">
                <SectionHeader title="Recent calls" subtitle="Open one to see it in its session." />
                <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                    {recentCallsLoading && recentCalls.length === 0 ? (
                        <Skeleton className="h-40 rounded-none" aria-busy />
                    ) : recentCalls.length === 0 ? (
                        <div className="p-4 text-sm text-secondary">No calls in this date range.</div>
                    ) : (
                        <div className="divide-y divide-primary">
                            {recentCalls.map((call) => (
                                <ExampleCallRow
                                    key={call.uuid}
                                    call={call}
                                    kinds={call.isError ? ['errored'] : []}
                                    onOpen={setOpenedCall}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-3">
                <SectionHeader title="Top usage" />
                <ToggleGroup
                    className="self-start"
                    value={[topTab]}
                    onValueChange={(next) => next[0] && setTopTab(next[0] as PersonTopDimension)}
                    aria-label="Top usage breakdown"
                >
                    {TOP_TABS.map((tab) => (
                        <ToggleGroupItem
                            key={tab.value}
                            value={tab.value}
                            size="sm"
                            data-attr={`mcp-person-top-${tab.value}`}
                        >
                            {tab.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <ResultTable
                    key={topTab}
                    rows={topRows?.[topTab] ?? []}
                    loading={topRowsLoading && !topRows}
                    pageSize={5}
                    columns={[
                        {
                            header: TOP_LABEL[topTab].header,
                            expand: true,
                            render: (r) => TOP_LABEL[topTab].render(String(r[0] ?? '')),
                        },
                        { header: 'Calls', align: 'right', render: (r) => formatNumber(Number(r[1] ?? 0)) },
                        { header: 'Errors', align: 'right', render: (r) => formatNumber(Number(r[2] ?? 0)) },
                        { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                    ]}
                />
            </div>

            {openedCall ? (
                <SessionDrawer
                    sessionId={openedCall.sessionId}
                    timestamp={openedCall.timestamp}
                    focusedEventId={openedCall.uuid}
                    stacked
                    onClose={() => setOpenedCall(null)}
                    dataAttr="mcp-person-session-drawer"
                />
            ) : null}
        </div>
    )
}
