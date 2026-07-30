import { useActions, useValues } from 'kea'

import { IconRefresh, IconSparkles, IconWarning } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import {
    Badge,
    Button,
    Progress,
    Skeleton,
    Spinner,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { MCPIntentClusterApi, MCPIntentClusterToolEntryApi } from '../generated/api.schemas'
import { KPI_MIN_SESSIONS } from './clusteringScorecards'
import { ClusterJourneySankey } from './ClusterJourneySankey'
import { ClusterSortKey, mcpClusteringLogic } from './mcpClusteringLogic'

const SORT_LABELS: Record<ClusterSortKey, string> = {
    calls: 'Calls',
    errors: 'Error rate',
    entropy: 'Routing entropy',
    concentration: 'Top-tool %',
}

function EntropyBadge({ entropy }: { entropy: number }): JSX.Element {
    if (entropy < 0.3) {
        return (
            <Tooltip title={`Routing entropy ${entropy.toFixed(2)} — one tool dominates this cluster's calls.`}>
                <span>
                    <Badge variant="success">Concentrated · {entropy.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    if (entropy < 0.6) {
        return (
            <Tooltip title={`Routing entropy ${entropy.toFixed(2)} — calls split between a few tools.`}>
                <span>
                    <Badge variant="warning">Mixed · {entropy.toFixed(2)}</Badge>
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip
            title={`Routing entropy ${entropy.toFixed(2)} — calls spread across many tools. Either a real multi-step workflow or the agent is improvising; the aggregate alone can't tell.`}
        >
            <span>
                <Badge variant="destructive">Spread · {entropy.toFixed(2)}</Badge>
            </span>
        </Tooltip>
    )
}

const TOP_TOOL_CHIPS = 3

function ToolChips({ distribution }: { distribution: readonly MCPIntentClusterToolEntryApi[] }): JSX.Element {
    if (distribution.length === 0) {
        return <span className="text-xs text-muted">No tool calls</span>
    }
    const top = distribution.slice(0, TOP_TOOL_CHIPS)
    const remainder = distribution.length - top.length
    return (
        <div className="flex flex-wrap items-center gap-1">
            {top.map((entry) => (
                <Tooltip
                    key={entry.tool}
                    title={
                        <div className="flex flex-col gap-0.5">
                            <span className="font-semibold">{entry.tool}</span>
                            <span>{entry.count.toLocaleString()} calls</span>
                            <span>{entry.pct.toFixed(1)}% of cluster</span>
                            {entry.error_rate_pct > 0 ? (
                                <span className="text-danger">{entry.error_rate_pct.toFixed(1)}% errors</span>
                            ) : null}
                        </div>
                    }
                >
                    <span
                        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-mono bg-surface-secondary ${
                            entry.error_rate_pct > 5 ? 'text-danger' : ''
                        }`}
                    >
                        {entry.tool}
                        <span className="text-muted tabular-nums">{Math.round(entry.pct)}%</span>
                    </span>
                </Tooltip>
            ))}
            {remainder > 0 ? <span className="text-[11px] text-muted">+{remainder} more</span> : null}
        </div>
    )
}

function Scorecards(): JSX.Element {
    const { concentratedRoutes, spreadRoutes, topErrorRoute, clusters, totalClusterCount } =
        useValues(mcpClusteringLogic)

    const concentratedShare =
        concentratedRoutes.total > 0 ? Math.round((100 * concentratedRoutes.focused) / concentratedRoutes.total) : 0

    return (
        <div className="flex flex-col gap-1">
            {totalClusterCount > clusters.length ? (
                <div className="text-xs text-muted">
                    Scorecards cover the top {clusters.length} of {totalClusterCount} clusters by call volume.
                </div>
            ) : null}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="bg-surface-primary border rounded p-3 min-h-[88px] flex flex-col">
                    <span className="text-muted text-xs font-medium uppercase">Concentrated routes</span>
                    <div className="flex items-baseline gap-2 mt-1">
                        <span className="text-2xl font-semibold">
                            {concentratedRoutes.focused}
                            <span className="text-muted text-base"> / {concentratedRoutes.total}</span>
                        </span>
                        <span className="text-xs text-muted">({concentratedShare}%)</span>
                    </div>
                    <span className="text-xs text-muted mt-1">
                        Intent groups with {KPI_MIN_SESSIONS}+ sessions where one tool handles at least 80% of calls.
                    </span>
                </div>
                <div className="bg-surface-primary border rounded p-3 min-h-[88px] flex flex-col">
                    <span className="text-muted text-xs font-medium uppercase">Spread routes</span>
                    <div className="flex items-baseline gap-2 mt-1">
                        <span className="text-2xl font-semibold">{spreadRoutes}</span>
                        <span className="text-xs text-muted">of {concentratedRoutes.total}</span>
                    </div>
                    <span className="text-xs text-muted mt-1">
                        Intent groups with {KPI_MIN_SESSIONS}+ sessions where no single tool covers half the calls.
                        Possible routing drift.
                    </span>
                </div>
                <div className="bg-surface-primary border rounded p-3 min-h-[88px] flex flex-col">
                    <span className="text-muted text-xs font-medium uppercase">Top error route</span>
                    {topErrorRoute ? (
                        <>
                            <div className="flex items-baseline gap-2 mt-1">
                                <span className="text-2xl font-semibold text-danger">
                                    {topErrorRoute.error_rate_pct.toFixed(1)}%
                                </span>
                                <span className="text-xs text-muted">over {topErrorRoute.call_count} calls</span>
                            </div>
                            <span className="text-xs text-muted mt-1 truncate" title={topErrorRoute.label}>
                                {topErrorRoute.label}
                            </span>
                        </>
                    ) : (
                        <>
                            <div className="flex items-baseline gap-2 mt-1">
                                <span className="text-2xl font-semibold text-success">0%</span>
                            </div>
                            <span className="text-xs text-muted mt-1">
                                No errors among intent groups with {KPI_MIN_SESSIONS}+ sessions.
                            </span>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}

function SortHeader(): JSX.Element {
    const { sortKey } = useValues(mcpClusteringLogic)
    const { setSortKey } = useActions(mcpClusteringLogic)
    return (
        <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted">Sort clusters by</span>
            {(Object.keys(SORT_LABELS) as ClusterSortKey[]).map((key) => (
                <Button
                    key={key}
                    size="sm"
                    variant={sortKey === key ? 'default' : 'outline'}
                    onClick={() => setSortKey(key)}
                >
                    {SORT_LABELS[key]}
                </Button>
            ))}
        </div>
    )
}

function ClusterList(): JSX.Element {
    const { visibleClusters, hiddenClusterCount, longTail, selectedClusterId } = useValues(mcpClusteringLogic)
    const { selectCluster, showAllClusters } = useActions(mcpClusteringLogic)

    if (visibleClusters.length === 0 && !longTail) {
        return (
            <div className="bg-surface-primary border rounded p-4 text-center text-muted text-sm">
                No intent clusters in this window.
            </div>
        )
    }

    return (
        <div className="bg-surface-primary border rounded" data-quill>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Intent cluster</TableHead>
                        <TableHead>Top tools</TableHead>
                        <TableHead align="right">Calls</TableHead>
                        <TableHead align="right">Errors</TableHead>
                        <TableHead>Routing</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {visibleClusters.map((cluster) => {
                        const isSelected = cluster.id === selectedClusterId
                        return (
                            <TableRow
                                key={cluster.id}
                                onClick={() => selectCluster(cluster.id)}
                                className={`cursor-pointer transition-colors ${
                                    isSelected ? 'bg-accent/10' : 'hover:bg-surface-secondary/60'
                                }`}
                            >
                                <TableCell expand>
                                    <div className="flex flex-col max-w-[480px]">
                                        <span className="font-medium truncate" title={cluster.label}>
                                            {cluster.label}
                                        </span>
                                        <span className="text-[10px] text-muted">
                                            {cluster.session_count} session
                                            {cluster.session_count === 1 ? '' : 's'} · {cluster.intent_count} intent
                                            {cluster.intent_count === 1 ? '' : 's'}
                                        </span>
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <ToolChips distribution={cluster.tool_distribution} />
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums text-xs">{cluster.call_count.toLocaleString()}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span
                                        className={`tabular-nums text-xs ${
                                            cluster.error_rate_pct > 5 ? 'text-danger font-semibold' : ''
                                        }`}
                                    >
                                        {cluster.error_rate_pct.toFixed(1)}%
                                    </span>
                                </TableCell>
                                <TableCell>
                                    <EntropyBadge entropy={cluster.routing_entropy} />
                                </TableCell>
                            </TableRow>
                        )
                    })}
                    {longTail ? (
                        <TableRow>
                            <TableCell expand>
                                <div className="flex flex-col">
                                    <Tooltip
                                        title={
                                            <div className="flex flex-col gap-1 max-w-md">
                                                <span className="font-semibold">Sample one-off intents</span>
                                                {longTail.sample_intents.map((intent, idx) => (
                                                    <span key={idx} className="text-xs">
                                                        &ldquo;{intent}&rdquo;
                                                    </span>
                                                ))}
                                            </div>
                                        }
                                    >
                                        <span className="font-medium text-muted cursor-help">
                                            Long tail: {longTail.intent_count.toLocaleString()} one-off intents
                                        </span>
                                    </Tooltip>
                                    <span className="text-[10px] text-muted">
                                        {longTail.session_count.toLocaleString()} session
                                        {longTail.session_count === 1 ? '' : 's'} that didn&apos;t group with anything
                                        else
                                    </span>
                                </div>
                            </TableCell>
                            <TableCell>
                                <span className="text-xs text-muted">Varied</span>
                            </TableCell>
                            <TableCell align="right">
                                <span className="tabular-nums text-xs">{longTail.call_count.toLocaleString()}</span>
                            </TableCell>
                            <TableCell align="right">
                                <span
                                    className={`tabular-nums text-xs ${
                                        longTail.error_rate_pct > 5 ? 'text-danger font-semibold' : ''
                                    }`}
                                >
                                    {longTail.error_rate_pct.toFixed(1)}%
                                </span>
                            </TableCell>
                            <TableCell>
                                <span className="text-xs text-muted">n/a</span>
                            </TableCell>
                        </TableRow>
                    ) : null}
                </TableBody>
            </Table>
            {hiddenClusterCount > 0 ? (
                <div className="flex flex-wrap items-center gap-3 border-t border-primary px-3 py-2 text-xs text-muted">
                    <span>
                        Showing the top {visibleClusters.length} of {visibleClusters.length + hiddenClusterCount}{' '}
                        clusters.
                    </span>
                    <Button size="sm" variant="outline" onClick={showAllClusters}>
                        Show all
                    </Button>
                </div>
            ) : null}
        </div>
    )
}

function RecurringIntentsSection(): JSX.Element | null {
    const { recurring } = useValues(mcpClusteringLogic)
    if (recurring.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col">
                <h3 className="text-base font-semibold">Recurring automated intents</h3>
                <span className="text-xs text-muted">
                    The same intent text opened 3 or more sessions in this window. These are usually scheduled agents
                    and crons, so they are listed here instead of the clusters above.
                </span>
            </div>
            <div className="bg-surface-primary border rounded" data-quill>
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Intent</TableHead>
                            <TableHead align="right">Sessions</TableHead>
                            <TableHead align="right">Calls</TableHead>
                            <TableHead align="right">Errors</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {recurring.map((entry) => (
                            <TableRow key={entry.intent_text}>
                                <TableCell expand>
                                    <span className="text-xs truncate block max-w-[560px]" title={entry.intent_text}>
                                        {entry.intent_text}
                                    </span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums text-xs">{entry.session_count.toLocaleString()}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums text-xs">{entry.call_count.toLocaleString()}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span
                                        className={`tabular-nums text-xs ${
                                            entry.error_rate_pct > 5 ? 'text-danger font-semibold' : ''
                                        }`}
                                    >
                                        {entry.error_rate_pct.toFixed(1)}%
                                    </span>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    )
}

function ClusterDetail({ cluster }: { cluster: MCPIntentClusterApi }): JSX.Element {
    const worstTool = [...cluster.tool_distribution].sort((a, b) => b.error_rate_pct - a.error_rate_pct)[0]
    return (
        <div className="bg-surface-primary border rounded p-4 flex flex-col gap-4">
            <header className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs uppercase text-muted font-medium">Selected cluster</span>
                        <h3 className="text-lg font-semibold leading-tight">{cluster.label}</h3>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                        <EntropyBadge entropy={cluster.routing_entropy} />
                        <Badge variant={cluster.error_rate_pct > 5 ? 'destructive' : 'default'}>
                            {cluster.error_rate_pct.toFixed(1)}% errors
                        </Badge>
                        <Badge variant="default">{cluster.call_count.toLocaleString()} calls</Badge>
                        <Badge variant="default">
                            {cluster.session_count} session{cluster.session_count === 1 ? '' : 's'}
                        </Badge>
                        <Badge variant="default">
                            {cluster.intent_count} intent{cluster.intent_count === 1 ? '' : 's'}
                        </Badge>
                    </div>
                </div>
                {worstTool && worstTool.error_rate_pct > 0 ? (
                    <div className="flex items-center gap-1 text-xs text-muted">
                        <IconWarning className="text-danger" />
                        Weakest tool in this cluster: <span className="font-mono">{worstTool.tool}</span>
                        <span className="text-danger ml-1">{worstTool.error_rate_pct.toFixed(1)}% errors</span>
                    </div>
                ) : null}
            </header>

            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-muted font-medium">Sample intents in this cluster</span>
                {cluster.sample_intents.length === 0 ? (
                    <div className="text-sm text-muted">No representative intents recorded.</div>
                ) : (
                    <div className="flex flex-col gap-2">
                        {cluster.sample_intents.map((intent, idx) => (
                            <div
                                key={idx}
                                className="bg-surface-secondary rounded p-2 text-xs font-mono leading-relaxed"
                            >
                                <span className="text-muted mr-1">&ldquo;</span>
                                {intent}
                                <span className="text-muted ml-1">&rdquo;</span>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-muted font-medium">Tool routing breakdown</span>
                <div data-quill>
                    <Table fullWidth>
                        <TableHeader>
                            <TableRow>
                                <TableHead expand>Tool</TableHead>
                                <TableHead align="right">Calls</TableHead>
                                <TableHead>Share of cluster</TableHead>
                                <TableHead align="right">Errors</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {cluster.tool_distribution.map((row) => (
                                <TableRow key={row.tool}>
                                    <TableCell expand>
                                        <span className="font-mono">{row.tool}</span>
                                    </TableCell>
                                    <TableCell align="right">{row.count.toLocaleString()}</TableCell>
                                    <TableCell>
                                        <div className="flex min-w-[160px] items-center gap-2">
                                            <Progress value={row.pct} className="flex-1" />
                                            <span className="w-10 text-right text-xs tabular-nums text-muted">
                                                {row.pct.toFixed(1)}%
                                            </span>
                                        </div>
                                    </TableCell>
                                    <TableCell align="right">
                                        {row.error_rate_pct > 0 ? (
                                            <span className="tabular-nums text-danger">
                                                {row.error_rate_pct.toFixed(1)}%{' '}
                                                <span className="text-muted">({row.errors})</span>
                                            </span>
                                        ) : (
                                            <span className="text-muted">0%</span>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </section>

            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-muted font-medium">Agent journeys</span>
                <ClusterJourneySankey journey={cluster.journey ?? null} />
            </section>
        </div>
    )
}

function StatusRow(): JSX.Element | null {
    const { snapshot, isComputing, clusters, totalClusterCount } = useValues(mcpClusteringLogic)
    const { recompute } = useActions(mcpClusteringLogic)
    if (snapshot.status === 'error') {
        return null
    }
    if (isComputing) {
        return (
            <div className="flex items-center gap-2 text-sm text-muted">
                <Spinner />
                Embedding intents and clustering — usually 30–60 seconds.
            </div>
        )
    }
    if (snapshot.last_computed_at) {
        const meta = snapshot.computed_with
        return (
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                    <span>Last computed</span>
                    <TZLabel time={snapshot.last_computed_at} />
                    {meta ? (
                        <>
                            <span>·</span>
                            <span>
                                {totalClusterCount > clusters.length
                                    ? `top ${clusters.length} of ${totalClusterCount} clusters`
                                    : `${totalClusterCount} clusters`}
                            </span>
                            <span>·</span>
                            <span>{meta.n_intents} intents</span>
                            <span>·</span>
                            <span>cosine threshold {meta.distance_threshold.toFixed(2)}</span>
                        </>
                    ) : null}
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={recompute}
                    data-attr="mcp-analytics-intent-clusters-recompute"
                >
                    <IconRefresh />
                    Recompute
                </Button>
            </div>
        )
    }
    return null
}

function EmptyState(): JSX.Element {
    const { recompute } = useActions(mcpClusteringLogic)
    const { snapshotLoading } = useValues(mcpClusteringLogic)
    return (
        <div
            className="bg-surface-primary border rounded p-8 flex flex-col items-center text-center gap-3 max-w-2xl mx-auto"
            data-quill
        >
            <IconSparkles className="text-4xl text-accent" />
            <h3 className="text-lg font-semibold">No intent clusters yet</h3>
            <p className="text-sm text-muted max-w-md">
                Clustering groups your agents&apos; session-level goals into themes, then shows which tools each theme
                routes to. It surfaces whether your MCP sends similar goals to the same tools, and which routes are the
                most error-prone.
            </p>
            <Button variant="default" onClick={recompute} disabled={snapshotLoading}>
                {snapshotLoading ? <Spinner /> : <IconSparkles />}
                Compute intent clusters
            </Button>
            <span className="text-xs text-muted">
                Needs sessions with a summarized intent — usually a few minutes after sessions are recorded.
            </span>
        </div>
    )
}

function ComputingSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
            </div>
            <Skeleton className="h-96 w-full" />
            <Skeleton className="h-48 w-full" />
        </div>
    )
}

export function MCPAnalyticsClustering(): JSX.Element {
    const { snapshot, selectedCluster, hasSnapshot, isComputing, snapshotLoading } = useValues(mcpClusteringLogic)
    const { recompute } = useActions(mcpClusteringLogic)

    if (snapshot.status === 'error') {
        return (
            <div className="flex flex-col gap-3">
                <LemonBanner type="error" action={{ children: 'Retry', onClick: recompute }}>
                    {snapshot.error_message || 'The last clustering run failed.'}
                </LemonBanner>
            </div>
        )
    }

    if (!hasSnapshot && !isComputing && !snapshotLoading) {
        return <EmptyState />
    }

    if (isComputing || (snapshotLoading && !hasSnapshot)) {
        return (
            <div className="flex flex-col gap-4" data-quill>
                <StatusRow />
                <ComputingSkeleton />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4" data-quill>
            <StatusRow />
            <Scorecards />
            <SortHeader />
            <ClusterList />
            {selectedCluster ? (
                <ClusterDetail cluster={selectedCluster} />
            ) : (
                <div className="bg-surface-primary border rounded p-6 text-center text-muted text-sm">
                    Click a cluster row above to see its sample intents and tool breakdown.
                </div>
            )}
            <RecurringIntentsSection />
        </div>
    )
}
