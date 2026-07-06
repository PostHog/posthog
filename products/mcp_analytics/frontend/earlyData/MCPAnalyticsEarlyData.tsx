import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconClock, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { Card } from '../dashboard/Card'
import { formatMs, formatNumber } from '../dashboard/formatters'
import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import type { ChecklistItem, EarlyRecentCall, EarlyToolRow } from './mcpEarlyDataLogic'
import { mcpEarlyDataLogic } from './mcpEarlyDataLogic'

/**
 * Progressive small-data view, shown between the first tool call and the volume
 * threshold where the windowed dashboard stops looking empty. Everything here is
 * all-time rather than windowed, refreshes on a timer, and frames low volume as
 * progress ("what unlocks next") instead of emptiness.
 */
export function MCPAnalyticsEarlyData(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-attr="mcp-analytics-early-data">
            <ProgressHeader />
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 flex flex-col gap-4">
                    <LiveActivityCard />
                    <TopToolsCard />
                </div>
                <div className="flex flex-col gap-4">
                    <StatsCard />
                    <ChecklistCard />
                </div>
            </div>
        </div>
    )
}

function ProgressHeader(): JSX.Element {
    const { signals } = useValues(mcpAnalyticsOnboardingLogic)
    const { setDashboardModeOverride } = useActions(mcpAnalyticsOnboardingLogic)
    const { stats, milestones, nextMilestone, milestoneProgress } = useValues(mcpEarlyDataLogic)

    const totalCalls = signals?.toolCallsTotal ?? 0
    const summaryParts = [
        `${formatNumber(totalCalls)} tool call${totalCalls === 1 ? '' : 's'}`,
        stats.distinctTools > 0 ? `across ${stats.distinctTools} tool${stats.distinctTools === 1 ? '' : 's'}` : null,
        stats.distinctClients > 0
            ? `from ${stats.distinctClients} client${stats.distinctClients === 1 ? '' : 's'}`
            : null,
    ].filter(Boolean)

    return (
        <Card>
            <div className="flex flex-col gap-3">
                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div>
                        <h3 className="text-lg font-semibold m-0">
                            {summaryParts.join(' ')}
                            {signals?.firstCallAt ? (
                                <span className="text-muted font-normal">
                                    {' '}
                                    since <TZLabel time={signals.firstCallAt} formatDate="MMM D" formatTime="" />
                                </span>
                            ) : null}
                        </h3>
                        <p className="text-muted text-sm m-0 mt-1">
                            Your MCP server is warming up. This view fills in live as agents use it
                            {nextMilestone
                                ? ` — next up: ${nextMilestone.unlocks.toLowerCase()} at ${formatNumber(nextMilestone.threshold)} calls.`
                                : '.'}
                        </p>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setDashboardModeOverride('full')}
                        data-attr="mcp-analytics-early-view-full-dashboard"
                    >
                        View full dashboard
                    </LemonButton>
                </div>
                <LemonProgress percent={milestoneProgress * 100} />
                <div className="flex gap-2 flex-wrap">
                    {milestones.map((milestone) => (
                        <Tooltip
                            key={milestone.key}
                            title={`${formatNumber(milestone.threshold)} tool call${milestone.threshold === 1 ? '' : 's'}`}
                        >
                            <LemonTag
                                type={milestone.reached ? 'success' : 'muted'}
                                icon={milestone.reached ? <IconCheckCircle /> : <IconClock />}
                            >
                                {milestone.unlocks}
                            </LemonTag>
                        </Tooltip>
                    ))}
                </div>
            </div>
        </Card>
    )
}

function LiveActivityCard(): JSX.Element {
    const { recentCalls, recentCallsLoading } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="Live activity">
            <LemonTable<EarlyRecentCall>
                dataSource={recentCalls}
                loading={recentCallsLoading && recentCalls.length === 0}
                rowKey={(row) => `${row.timestamp}-${row.tool}`}
                emptyState="Waiting for the next tool call…"
                columns={[
                    {
                        title: 'When',
                        key: 'timestamp',
                        width: 130,
                        render: (_, row) => <TZLabel time={row.timestamp} />,
                    },
                    {
                        title: 'Tool',
                        key: 'tool',
                        render: (_, row) => (
                            <span className="flex items-center gap-1 font-mono text-xs">
                                {row.tool}
                                {row.isError ? <LemonTag type="danger">error</LemonTag> : null}
                            </span>
                        ),
                    },
                    {
                        title: 'Agent intent',
                        key: 'intent',
                        render: (_, row) =>
                            row.intent ? (
                                <span className="text-sm">{row.intent}</span>
                            ) : (
                                <span className="text-muted text-sm">—</span>
                            ),
                    },
                    {
                        title: 'Duration',
                        key: 'duration',
                        width: 90,
                        align: 'right',
                        render: (_, row) => (row.durationMs == null ? '—' : formatMs(row.durationMs)),
                    },
                    {
                        title: 'Client',
                        key: 'client',
                        width: 140,
                        render: (_, row) => row.clientName ?? <span className="text-muted">unknown</span>,
                    },
                ]}
            />
        </Card>
    )
}

function TopToolsCard(): JSX.Element {
    const { topTools, topToolsLoading } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="Most-used tools">
            <LemonTable<EarlyToolRow>
                dataSource={topTools}
                loading={topToolsLoading && topTools.length === 0}
                rowKey="tool"
                emptyState="No tool calls yet"
                columns={[
                    {
                        title: 'Tool',
                        key: 'tool',
                        render: (_, row) => <span className="font-mono text-xs">{row.tool}</span>,
                    },
                    { title: 'Calls', key: 'calls', width: 90, align: 'right', render: (_, row) => row.calls },
                    {
                        title: 'Errors',
                        key: 'errors',
                        width: 90,
                        align: 'right',
                        render: (_, row) =>
                            row.errors > 0 ? <span className="text-danger">{row.errors}</span> : row.errors,
                    },
                ]}
            />
        </Card>
    )
}

function StatsCard(): JSX.Element {
    const { stats } = useValues(mcpEarlyDataLogic)
    const errorRate = stats.totalCalls > 0 ? (stats.errorCalls / stats.totalCalls) * 100 : 0

    const tiles: Array<{ label: string; value: string }> = [
        { label: 'Tool calls', value: formatNumber(stats.totalCalls) },
        { label: 'Tools used', value: formatNumber(stats.distinctTools) },
        { label: 'Sessions', value: formatNumber(stats.distinctSessions) },
        { label: 'Error rate', value: stats.totalCalls > 0 ? `${errorRate.toFixed(1)}%` : '—' },
    ]

    return (
        <Card title="All-time totals">
            <div className="grid grid-cols-2 gap-3">
                {tiles.map((tile) => (
                    <div key={tile.label}>
                        <div className="text-2xl font-semibold">{tile.value}</div>
                        <div className="text-muted text-xs">{tile.label}</div>
                    </div>
                ))}
            </div>
        </Card>
    )
}

const CHECKLIST_ICONS: Record<ChecklistItem['status'], JSX.Element> = {
    ok: <IconCheckCircle className="text-success shrink-0 mt-0.5" />,
    warning: <IconWarning className="text-warning shrink-0 mt-0.5" />,
    pending: <IconClock className="text-muted shrink-0 mt-0.5" />,
}

function ChecklistCard(): JSX.Element {
    const { checklist } = useValues(mcpEarlyDataLogic)

    return (
        <Card title="Instrumentation checklist">
            <div className="flex flex-col gap-3">
                {checklist.map((item) => (
                    <div key={item.key} className="flex gap-2">
                        {CHECKLIST_ICONS[item.status]}
                        <div>
                            <div className="text-sm font-medium">{item.title}</div>
                            <div className="text-muted text-xs">
                                {item.detail} {item.status !== 'ok' ? <Link to={item.docsUrl}>Set up</Link> : null}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </Card>
    )
}
