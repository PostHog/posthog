import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronLeft, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

import { InsightsViewMode, errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

function buildExceptionVolumeQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: null, name: 'All events' }],
            properties: [
                {
                    key: 'event',
                    type: PropertyFilterType.Event,
                    value: '$exception',
                    operator: PropertyOperator.Exact,
                },
            ],
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsBar },
        },
        showHeader: false,
        showTable: false,
    }
}

function buildCrashFreeSessionsQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: null,
                    name: 'Total sessions',
                    math: BaseMathType.UniqueSessions,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    name: 'Sessions with crash',
                    math: BaseMathType.UniqueSessions,
                },
            ],
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
        },
        showHeader: false,
        showTable: false,
    }
}

function TimeRangeControls(): JSX.Element {
    const { viewMode, dateLabel, canNavigateForward } = useValues(errorTrackingInsightsLogic)
    const { setViewMode, navigateBack, navigateForward } = useActions(errorTrackingInsightsLogic)

    return (
        <div className="flex items-center gap-2">
            <LemonSegmentedButton
                size="small"
                value={viewMode}
                onChange={(value) => setViewMode(value as InsightsViewMode)}
                options={[
                    { value: 'week', label: 'Week' },
                    { value: 'month', label: 'Month' },
                ]}
            />
            <div className="flex items-center gap-1">
                <LemonButton size="small" icon={<IconChevronLeft />} onClick={navigateBack} />
                <span className="text-sm font-medium min-w-48 text-center select-none">{dateLabel}</span>
                <LemonButton
                    size="small"
                    icon={<IconChevronRight />}
                    onClick={navigateForward}
                    disabledReason={!canNavigateForward ? "You're viewing the current period" : undefined}
                />
            </div>
        </div>
    )
}

function formatNumber(n: number): string {
    if (n >= 1_000_000) {
        return `${(n / 1_000_000).toFixed(1)}M`
    }
    if (n >= 1_000) {
        return `${(n / 1_000).toFixed(1)}K`
    }
    return n.toLocaleString()
}

function SummaryStats(): JSX.Element {
    const { summaryStats, summaryStatsLoading } = useValues(errorTrackingInsightsLogic)

    const cards = [
        { label: 'Total exceptions', value: summaryStats ? formatNumber(summaryStats.totalExceptions) : null },
        { label: 'Total sessions', value: summaryStats ? formatNumber(summaryStats.totalSessions) : null },
        { label: 'Sessions with crash', value: summaryStats ? formatNumber(summaryStats.crashSessions) : null },
        { label: 'Crash-free sessions', value: summaryStats ? `${summaryStats.crashFreeRate}%` : null },
    ]

    return (
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
            {cards.map(({ label, value }) => (
                <div key={label} className="border rounded-lg bg-surface-primary p-4 flex flex-col gap-1">
                    <span className="text-xs text-secondary">{label}</span>
                    {summaryStatsLoading ? (
                        <LemonSkeleton className="h-8 w-20" />
                    ) : (
                        <span className="text-2xl font-bold">{value ?? '—'}</span>
                    )}
                </div>
            ))}
        </div>
    )
}

function ChartCard({
    title,
    description,
    query,
}: {
    title: string
    description: string
    query: InsightVizNode<TrendsQuery>
}): JSX.Element {
    return (
        <div className="border rounded-lg bg-surface-primary flex flex-col h-100">
            <div className="flex items-center justify-between px-4 pt-3 pb-1 shrink-0">
                <div>
                    <h3 className="font-semibold text-sm m-0">{title}</h3>
                    <p className="text-xs text-secondary m-0">{description}</p>
                </div>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconExternal />}
                    to={urls.insightNew({ query })}
                    targetBlank
                >
                    Open as insight
                </LemonButton>
            </div>
            <div className="ErrorTracking__insights flex-1 min-h-0 p-2">
                <Query query={query} readOnly={true} />
            </div>
        </div>
    )
}

export function ErrorTrackingInsights(): JSX.Element {
    const { dateFrom, chartDateTo } = useValues(errorTrackingInsightsLogic)

    const exceptionVolumeQuery = useMemo(
        () => buildExceptionVolumeQuery(dateFrom, chartDateTo),
        [dateFrom, chartDateTo]
    )
    const crashFreeQuery = useMemo(() => buildCrashFreeSessionsQuery(dateFrom, chartDateTo), [dateFrom, chartDateTo])

    return (
        <div className="space-y-4 mt-4">
            <TimeRangeControls />
            <SummaryStats />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Exception volume" description="Exceptions per day" query={exceptionVolumeQuery} />
                <ChartCard
                    title="Crash-free sessions"
                    description="Percentage of sessions without any exceptions"
                    query={crashFreeQuery}
                />
            </div>
        </div>
    )
}
