import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronLeft, IconChevronRight, IconExternal } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

import { InsightsViewMode, errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

function buildExceptionVolumeQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$exception', name: 'Exceptions' }],
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsBar },
        },
        showHeader: false,
        showTable: false,
    }
}

function buildSessionsOverviewQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
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
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
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

function buildTotalExceptionsQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$exception', name: 'Exceptions' }],
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.BoldNumber },
        },
        showHeader: false,
        showTable: false,
    }
}

function buildCrashFreeRateNumberQuery(dateFrom: string, dateTo: string): InsightVizNode<TrendsQuery> {
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
                display: ChartDisplayType.BoldNumber,
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
        <div className="flex items-center justify-between">
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
        </div>
    )
}

function StatCard({ title, query }: { title: string; query: InsightVizNode<TrendsQuery> }): JSX.Element {
    return (
        <div className="border rounded-lg bg-surface-primary p-4 flex flex-col items-center justify-center min-h-28">
            <p className="text-xs text-secondary m-0 mb-1">{title}</p>
            <div className="[&_.BoldNumber]:!text-2xl [&_.BoldNumber__value]:!text-2xl [&_.InsightViz]:!border-0 [&_.InsightViz]:!shadow-none [&_.InsightViz]:!p-0">
                <Query query={query} readOnly={true} />
            </div>
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
    const { dateFrom, dateTo } = useValues(errorTrackingInsightsLogic)

    const exceptionVolumeQuery = useMemo(() => buildExceptionVolumeQuery(dateFrom, dateTo), [dateFrom, dateTo])
    const sessionsOverviewQuery = useMemo(() => buildSessionsOverviewQuery(dateFrom, dateTo), [dateFrom, dateTo])
    const crashFreeQuery = useMemo(() => buildCrashFreeSessionsQuery(dateFrom, dateTo), [dateFrom, dateTo])
    const totalExceptionsQuery = useMemo(() => buildTotalExceptionsQuery(dateFrom, dateTo), [dateFrom, dateTo])
    const crashFreeRateQuery = useMemo(() => buildCrashFreeRateNumberQuery(dateFrom, dateTo), [dateFrom, dateTo])

    return (
        <div className="space-y-4 mt-4">
            <TimeRangeControls />

            <div className="grid grid-cols-2 gap-4">
                <StatCard title="Total exceptions" query={totalExceptionsQuery} />
                <StatCard title="Crash-free sessions" query={crashFreeRateQuery} />
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <ChartCard title="Exception volume" description="Exceptions per day" query={exceptionVolumeQuery} />
                <ChartCard
                    title="Sessions overview"
                    description="Total sessions vs sessions with at least one crash"
                    query={sessionsOverviewQuery}
                />
            </div>

            <ChartCard
                title="Crash-free sessions"
                description="Percentage of sessions without any exceptions"
                query={crashFreeQuery}
            />
        </div>
    )
}
