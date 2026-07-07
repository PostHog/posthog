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

function HeatmapCell({
    entry,
    size,
    rowMaxCount,
}: {
    entry: MCPIntentClusterToolEntryApi | undefined
    size: number
    rowMaxCount: number
}): JSX.Element {
    const sizeStyle = { width: size, height: size }
    if (!entry || entry.count === 0) {
        return (
            <div
                className="rounded-[2px] bg-surface-secondary/30"
                // eslint-disable-next-line react/forbid-dom-props
                style={sizeStyle}
                aria-hidden
            />
        )
    }
    // Scale relative to the row's max — so the most-called tool in each
    // cluster is fully dark and the rest grade down. A 1-call tool next to
    // a 50-call tool still shows up clearly thanks to the 0.3 floor.
    const intensity = rowMaxCount > 0 ? entry.count / rowMaxCount : 0
    const opacity = Math.max(0.3, Math.min(1, intensity))
    const hasErrors = entry.error_rate_pct > 0
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-0.5">
                    <span className="font-semibold">{entry.tool}</span>
                    <span>{entry.count.toLocaleString()} calls</span>
                    <span>{entry.pct.toFixed(1)}% of cluster</span>
                    {hasErrors ? <span className="text-danger">{entry.error_rate_pct.toFixed(1)}% errors</span> : null}
                </div>
            }
        >
            <div
                className="rounded-[2px] cursor-help"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    ...sizeStyle,
                    backgroundColor: hasErrors ? 'var(--danger)' : 'var(--accent)',
                    opacity,
                }}
            />
        </Tooltip>
    )
}

function Scorecards(): JSX.Element {
    const { concentratedRoutes, spreadRoutes, topErrorRoute, clusters } = useValues(mcpClusteringLogic)

    const concentratedShare =
        concentratedRoutes.total > 0 ? Math.round((100 * concentratedRoutes.focused) / concentratedRoutes.total) : 0

    return (
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
                <span className="text-xs text-muted mt-1">Intent groups where one tool handles ≥80% of calls.</span>
            </div>
            <div className="bg-surface-primary border rounded p-3 min-h-[88px] flex flex-col">
                <span className="text-muted text-xs font-medium uppercase">Spread routes</span>
                <div className="flex items-baseline gap-2 mt-1">
                    <span className="text-2xl font-semibold">{spreadRoutes}</span>
                    <span className="text-xs text-muted">of {clusters.length}</span>
                </div>
                <span className="text-xs text-muted mt-1">
                    Intent groups where no single tool covers half the calls — possible drift.
                </span>
            </div>
            <div className="bg-surface-primary border rounded p-3 min-h-[88px] flex flex-col">
                <span className="text-muted text-xs font-medium uppercase">Top error route</span>
                {topErrorRoute && topErrorRoute.error_rate_pct > 0 ? (
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
                        <span className="text-xs text-muted mt-1">No errors observed across clusters.</span>
                    </>
                )}
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

function Heatmap(): JSX.Element {
    const { sortedClusters, toolColumns, selectedClusterId } = useValues(mcpClusteringLogic)
    const { selectCluster } = useActions(mcpClusteringLogic)

    if (toolColumns.length === 0) {
        return (
            <div className="bg-surface-primary border rounded p-4 text-center text-muted text-sm">
                No tool calls observed in any cluster yet.
            </div>
        )
    }

    // Spacious mode: few tools and shortish names. Bigger cells, horizontal labels.
    // Compact mode: many tools or long names. Github-style with rotated labels.
    const longestName = Math.max(...toolColumns.map((t) => t.length))
    const isSpacious = toolColumns.length <= 6 && longestName <= 14

    const cellSize = isSpacious ? 22 : 14
    const columnWidth = isSpacious ? 0 : 18 // 0 = let CSS auto-size to label width

    return (
        <div className="bg-surface-primary border rounded overflow-x-auto">
            <table className="text-sm border-collapse" style={{ borderSpacing: 0 }}>
                <thead>
                    <tr className="bg-surface-secondary text-[10px] text-muted">
                        <th className="text-left px-3 py-2 sticky left-0 bg-surface-secondary z-10 min-w-[220px] align-bottom text-xs">
                            Intent cluster
                        </th>
                        {toolColumns.map((tool) =>
                            isSpacious ? (
                                <th
                                    key={tool}
                                    className="px-2 pb-1 pt-2 font-medium font-mono text-[11px] text-center align-bottom whitespace-nowrap"
                                    title={tool}
                                >
                                    {tool}
                                </th>
                            ) : (
                                <th
                                    key={tool}
                                    className="px-0 pb-1 pt-2 font-medium align-bottom"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: columnWidth, minWidth: columnWidth, maxWidth: columnWidth }}
                                >
                                    <div
                                        className="font-mono text-[10px] mx-auto whitespace-nowrap overflow-hidden text-ellipsis"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            writingMode: 'vertical-rl',
                                            transform: 'rotate(180deg)',
                                            height: 96,
                                            lineHeight: '18px',
                                        }}
                                        title={tool}
                                    >
                                        {tool}
                                    </div>
                                </th>
                            )
                        )}
                        <th className="px-3 py-2 text-right text-xs align-bottom">Calls</th>
                        <th className="px-3 py-2 text-right text-xs align-bottom">Errors</th>
                        <th className="px-3 py-2 text-left text-xs align-bottom">Routing</th>
                    </tr>
                </thead>
                <tbody>
                    {sortedClusters.map((cluster) => {
                        const isSelected = cluster.id === selectedClusterId
                        const byTool = new Map(cluster.tool_distribution.map((e) => [e.tool, e]))
                        const rowMaxCount = cluster.tool_distribution.reduce(
                            (max, entry) => Math.max(max, entry.count),
                            0
                        )
                        // Sticky cells need their own background — `tr` backgrounds don't paint
                        // through to sticky-positioned children when scrolled horizontally.
                        const rowBg = isSelected
                            ? 'bg-accent/10'
                            : 'bg-surface-primary group-hover:bg-surface-secondary/60'
                        return (
                            <tr
                                key={cluster.id}
                                onClick={() => selectCluster(cluster.id)}
                                className={`group border-t border-primary cursor-pointer transition-colors ${
                                    isSelected ? 'bg-accent/10' : 'hover:bg-surface-secondary/60'
                                }`}
                            >
                                <td
                                    className={`px-3 py-1.5 sticky left-0 z-10 min-w-[220px] max-w-[280px] transition-colors ${rowBg}`}
                                >
                                    <div className="flex flex-col">
                                        <span className="font-medium truncate" title={cluster.label}>
                                            {cluster.label}
                                        </span>
                                        <span className="text-[10px] text-muted">
                                            {cluster.session_count} session
                                            {cluster.session_count === 1 ? '' : 's'} · {cluster.intent_count} intent
                                            {cluster.intent_count === 1 ? '' : 's'}
                                        </span>
                                    </div>
                                </td>
                                {toolColumns.map((tool) => (
                                    <td
                                        key={tool}
                                        className="p-0 align-middle"
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={
                                            isSpacious
                                                ? undefined
                                                : { width: columnWidth, minWidth: columnWidth, maxWidth: columnWidth }
                                        }
                                    >
                                        <div className="flex justify-center items-center py-[2px]">
                                            <HeatmapCell
                                                entry={byTool.get(tool)}
                                                size={cellSize}
                                                rowMaxCount={rowMaxCount}
                                            />
                                        </div>
                                    </td>
                                ))}
                                <td className="px-3 py-1.5 text-right tabular-nums text-xs">
                                    {cluster.call_count.toLocaleString()}
                                </td>
                                <td
                                    className={`px-3 py-1.5 text-right tabular-nums text-xs ${
                                        cluster.error_rate_pct > 5 ? 'text-danger font-semibold' : ''
                                    }`}
                                >
                                    {cluster.error_rate_pct.toFixed(1)}%
                                </td>
                                <td className="px-3 py-1.5">
                                    <EntropyBadge entropy={cluster.routing_entropy} />
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
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
    const { snapshot, isComputing } = useValues(mcpClusteringLogic)
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
                            <span>{meta.n_clusters} clusters</span>
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
            <Heatmap />
            {selectedCluster ? (
                <ClusterDetail cluster={selectedCluster} />
            ) : (
                <div className="bg-surface-primary border rounded p-6 text-center text-muted text-sm">
                    Click a cluster row above to see its sample intents and tool breakdown.
                </div>
            )}
        </div>
    )
}
