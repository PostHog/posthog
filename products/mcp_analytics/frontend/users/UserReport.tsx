import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Badge, Skeleton, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { useChartTheme } from 'lib/charts/hooks'
import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { formatPercentage } from 'lib/utils/numbers'

import { labMark, modelLab } from '../aiLabs'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { HarnessLogo } from '../dashboard/harness'
import { HarnessLabel } from '../dashboard/HarnessLabel'
import { MetricTile } from '../dashboard/MetricTile'
import { deltaPct } from '../mcpDashboardOverviewLogic'
import { ResultTable, SectionHeader } from '../MCPToolReport'
import { SessionDrawer } from '../sessions/SessionDrawer'
import { formatDuration, sessionDurationMs } from '../sessions/utils'
import { type UserRecentSession, userReportLogic } from './userReportLogic'
import type { UserTopDimension } from './usersQueries'

const TOP_TABS: { value: UserTopDimension; label: string }[] = [
    { value: 'tools', label: 'Tools' },
    { value: 'harnesses', label: 'Harnesses' },
    { value: 'models', label: 'Models' },
]

// Tool and model names are raw event data from this person's calls, so keep them out of autocapture and replay.
const TOP_LABEL: Record<UserTopDimension, { header: string; render: (label: string) => JSX.Element }> = {
    tools: { header: 'Tool', render: (label) => <span className="ph-no-capture truncate font-mono">{label}</span> },
    harnesses: { header: 'Harness', render: (label) => <HarnessLabel category={label} /> },
    models: {
        header: 'Model',
        render: (label) =>
            label === 'Unknown' ? (
                <span className="text-muted">Unknown</span>
            ) : (
                <span className="flex items-center gap-1.5">
                    <BrandMark name={labMark(modelLab(label))} className="size-4 shrink-0" />
                    <span className="ph-no-capture truncate">{label}</span>
                </span>
            ),
    },
}

function RecentSessionRow({
    session,
    onOpen,
}: {
    session: UserRecentSession
    onOpen: (session: UserRecentSession) => void
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={() => onOpen(session)}
            // Intents are raw event data, so keep them out of autocapture and replay.
            className="ph-no-capture flex w-full cursor-pointer items-start justify-between gap-3 px-3 py-2 text-left hover:bg-fill-highlight-50"
            data-attr="mcp-user-recent-session"
        >
            <Tooltip title={session.harness || 'Unknown client'}>
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded border border-primary bg-surface-primary">
                    <HarnessLogo category={session.harness || 'Other'} className="size-4" />
                </span>
            </Tooltip>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                {session.tools.length ? (
                    <span className="truncate font-mono text-sm font-semibold">{session.tools.join(', ')}</span>
                ) : null}
                <span className={cn('line-clamp-1 text-sm', !session.intent && 'italic text-secondary')}>
                    {session.intent || 'No intent recorded'}
                </span>
                <span className="flex flex-wrap items-center gap-1.5 text-xs text-secondary">
                    <span>
                        {formatNumber(session.calls)} {session.calls === 1 ? 'call' : 'calls'}
                    </span>
                    {session.errors ? (
                        <Badge variant="destructive">
                            {formatNumber(session.errors)} {session.errors === 1 ? 'error' : 'errors'}
                        </Badge>
                    ) : null}
                    <TZLabel time={session.started} />
                </span>
            </span>
            <span className="shrink-0 text-sm tabular-nums">
                {formatDuration(sessionDurationMs(session.started, session.ended))}
            </span>
        </button>
    )
}

/** One user's report, on its page and in the Users drawer. Mount it under a `userReportLogic`. */
export function UserReport(): JSX.Element {
    const {
        totals,
        totalsLoading,
        totalsFailed,
        series,
        seriesLoading,
        interval,
        incompleteTail,
        topRows,
        topRowsLoading,
        recentSessions,
        recentSessionsLoading,
    } = useValues(userReportLogic)
    const { loadTotals } = useActions(userReportLogic)
    const theme = useChartTheme()
    const [topTab, setTopTab] = useState<UserTopDimension>('tools')
    const [openedSession, setOpenedSession] = useState<UserRecentSession | null>(null)

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
                                hasValue={!!totals && !!series}
                                failed={totalsFailed}
                                onRetry={loadTotals}
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
                <SectionHeader title="Recent sessions" />
                <div className="overflow-hidden rounded border border-primary bg-surface-primary">
                    {recentSessionsLoading && recentSessions.length === 0 ? (
                        <Skeleton className="h-40 rounded-none" aria-busy />
                    ) : recentSessions.length === 0 ? (
                        <div className="p-4 text-sm text-secondary">No sessions in this date range.</div>
                    ) : (
                        <div className="divide-y divide-primary">
                            {recentSessions.map((session) => (
                                <RecentSessionRow key={session.sessionId} session={session} onOpen={setOpenedSession} />
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
                    onValueChange={(next) => next[0] && setTopTab(next[0] as UserTopDimension)}
                    aria-label="Top usage breakdown"
                >
                    {TOP_TABS.map((tab) => (
                        <ToggleGroupItem
                            key={tab.value}
                            value={tab.value}
                            size="sm"
                            data-attr={`mcp-user-top-${tab.value}`}
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

            {openedSession ? (
                <SessionDrawer
                    sessionId={openedSession.sessionId}
                    timestamp={openedSession.started}
                    stacked
                    onClose={() => setOpenedSession(null)}
                    dataAttr="mcp-user-session-drawer"
                />
            ) : null}
        </div>
    )
}
