import { IconArrowRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import {
    Badge,
    Progress,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { urls } from '~/scenes/urls'

import type { MCPClusterSwitchApi, MCPIntentClusterApi, MCPToolPivotApi } from '../generated/api.schemas'
import { toolClusterRows } from './mcpClusteringLogic'

interface ToolSwitchRow extends MCPClusterSwitchApi {
    clusterLabel: string
}

/**
 * Every error switch across the snapshot that involves the given tool, worst first.
 * Clusters stored before switches were captured carry none: the schema marks the field
 * required, the stored JSONB does not, so it has to be treated as absent.
 */
function collectSwitches(tool: string, clusters: readonly MCPIntentClusterApi[]): ToolSwitchRow[] {
    const rows: ToolSwitchRow[] = []
    for (const cluster of clusters) {
        for (const sw of cluster.switches ?? []) {
            if (sw.from_tool === tool || sw.to_tool === tool) {
                rows.push({ ...sw, clusterLabel: cluster.label })
            }
        }
    }
    return rows.sort((a, b) => b.count - a.count).slice(0, 10)
}

export function ToolIntentDetail({
    tool,
    clusters,
    showToolLink = true,
    categories = [],
}: {
    tool: MCPToolPivotApi
    /** The snapshot's clusters — the pivot's entries carry only ids and join against these. */
    clusters: readonly MCPIntentClusterApi[]
    showToolLink?: boolean
    /**
     * Categories the tool is called under. Passed in rather than read from the clustering
     * logic, because the tool detail scene renders this without that logic mounted.
     */
    categories?: string[]
}): JSX.Element {
    const switches = collectSwitches(tool.tool, clusters)
    const clusterRows = toolClusterRows(tool, clusters)

    return (
        <div className="bg-surface-primary border rounded p-4 flex flex-col gap-4" data-quill>
            <header className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs uppercase text-muted font-medium">Selected tool</span>
                        {showToolLink ? (
                            <LinkPrimitive to={urls.mcpAnalyticsTool(tool.tool)}>
                                <h3 className="text-lg font-semibold leading-tight font-mono">{tool.tool}</h3>
                            </LinkPrimitive>
                        ) : (
                            <h3 className="text-lg font-semibold leading-tight font-mono">{tool.tool}</h3>
                        )}
                        {categories.length > 0 ? (
                            <div className="flex flex-wrap items-center gap-1">
                                {categories.map((category) => (
                                    <Badge key={category} variant="info">
                                        {category}
                                    </Badge>
                                ))}
                            </div>
                        ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2 shrink-0">
                        <Badge variant="default">{humanFriendlyNumber(tool.call_count)} calls</Badge>
                        <Badge variant="default">
                            {tool.session_count} session{tool.session_count === 1 ? '' : 's'}
                        </Badge>
                        {tool.discovery_rate_pct !== null ? (
                            <Tooltip
                                title={`Called in ${tool.called_when_advertised} of the ${tool.advertised_sessions} sampled sessions that advertised it.`}
                            >
                                <span>
                                    <Badge variant={tool.discovery_rate_pct < 25 ? 'destructive' : 'default'}>
                                        {tool.discovery_rate_pct.toFixed(1)}% discovery
                                    </Badge>
                                </span>
                            </Tooltip>
                        ) : null}
                    </div>
                </div>
                {tool.description ? (
                    <p className="text-xs text-muted font-mono bg-surface-secondary rounded p-2 mb-0">
                        {tool.description}
                    </p>
                ) : (
                    <p className="text-xs text-muted mb-0">
                        No description captured for this tool yet, so description fit can't be scored. Descriptions
                        appear as new calls are captured.
                    </p>
                )}
            </header>

            <section className="flex flex-col gap-2">
                <span className="text-xs uppercase text-muted font-medium">
                    Intents this tool serves
                    {tool.n_clusters_served > clusterRows.length
                        ? ` · top ${clusterRows.length} of ${tool.n_clusters_served}`
                        : ''}
                </span>
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Intent</TableHead>
                            <TableHead align="right">Calls</TableHead>
                            <TableHead>Capture</TableHead>
                            <TableHead>Strongest competitor</TableHead>
                            <TableHead align="right">Description fit</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {clusterRows.map(({ entry, cluster }) => (
                            <TableRow key={entry.cluster_id}>
                                <TableCell expand>
                                    <div className="flex flex-col">
                                        <span className="truncate max-w-[360px]" title={cluster.label}>
                                            {cluster.label}
                                        </span>
                                        <span className="text-[10px] text-muted">
                                            {entry.rank === 1
                                                ? 'Top tool for this intent'
                                                : `Rank ${entry.rank} for this intent`}
                                            {' · '}
                                            {humanFriendlyNumber(cluster.call_count)} calls in cluster
                                        </span>
                                    </div>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{humanFriendlyNumber(entry.calls)}</span>
                                </TableCell>
                                <TableCell>
                                    <div className="flex min-w-[140px] items-center gap-2">
                                        <Progress value={entry.capture_pct} className="flex-1" />
                                        <span className="w-10 text-right text-xs tabular-nums text-muted">
                                            {entry.capture_pct.toFixed(1)}%
                                        </span>
                                    </div>
                                </TableCell>
                                <TableCell>
                                    {entry.top_competitor ? (
                                        <span className="text-xs">
                                            <span className="font-mono">{entry.top_competitor.tool}</span>
                                            <span className="text-muted">
                                                {' '}
                                                takes {entry.top_competitor.pct.toFixed(1)}%
                                            </span>
                                        </span>
                                    ) : (
                                        <span className="text-muted text-xs">Only tool for this intent</span>
                                    )}
                                </TableCell>
                                <TableCell align="right">
                                    {entry.description_fit !== null ? (
                                        <span className="tabular-nums">{entry.description_fit.toFixed(2)}</span>
                                    ) : (
                                        <span className="text-muted">—</span>
                                    )}
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </section>

            {switches.length > 0 ? (
                <section className="flex flex-col gap-2">
                    <span className="text-xs uppercase text-muted font-medium">Error switches involving this tool</span>
                    <div className="flex flex-col gap-1">
                        {switches.map((row, index) => (
                            <div key={index} className="flex items-center gap-2 text-xs">
                                <span className={`font-mono ${row.from_tool === tool.tool ? 'text-danger' : ''}`}>
                                    {row.from_tool}
                                </span>
                                <IconArrowRight className="text-muted" />
                                <span className={`font-mono ${row.to_tool === tool.tool ? 'text-success' : ''}`}>
                                    {row.to_tool}
                                </span>
                                <span className="text-muted">
                                    ×{row.count} after errors, for "{row.clusterLabel}"
                                </span>
                            </div>
                        ))}
                    </div>
                    <span className="text-[10px] text-muted">
                        An errored call immediately followed by a different tool for the same intent. Switches away from
                        this tool suggest agents fall back elsewhere when it fails; switches into it suggest it picks up
                        after other tools fail.
                    </span>
                </section>
            ) : null}
        </div>
    )
}
