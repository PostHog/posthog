import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType } from '~/types'

function buildExceptionVolumeQuery(): InsightVizNode<TrendsQuery> {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$exception', name: 'Exceptions' }],
            interval: 'day',
            dateRange: { date_from: '-30d' },
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        },
        showHeader: false,
        showTable: false,
    }
}

function buildSessionsOverviewQuery(): InsightVizNode<TrendsQuery> {
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
            dateRange: { date_from: '-30d' },
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        },
        showHeader: false,
        showTable: false,
    }
}

function buildCrashFreeSessionsQuery(): InsightVizNode<TrendsQuery> {
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
            dateRange: { date_from: '-30d' },
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

function InsightCard({
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
                    <h3 className="font-semibold text-base m-0">{title}</h3>
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
    return (
        <div className="space-y-4 mt-4">
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <InsightCard
                    title="Exception volume"
                    description="Total exceptions per day over the last 30 days"
                    query={buildExceptionVolumeQuery()}
                />
                <InsightCard
                    title="Sessions overview"
                    description="Total sessions vs sessions with at least one crash"
                    query={buildSessionsOverviewQuery()}
                />
            </div>
            <InsightCard
                title="Crash-free sessions"
                description="Percentage of sessions without any exceptions"
                query={buildCrashFreeSessionsQuery()}
            />
        </div>
    )
}
