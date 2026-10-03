import { useValues } from 'kea'

import { IconArrowRight, IconRefresh, IconWarning } from '@posthog/icons'
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

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPIntentClusterApi } from '../generated/api.schemas'
import { ClusterJourneySankey } from './ClusterJourneySankey'
import { EntropyBadge } from './EntropyBadge'
import { clusterCategories, mcpClusteringLogic } from './mcpClusteringLogic'

function SectionLabel({ children, hint }: { children: string; hint?: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs uppercase text-muted font-medium">{children}</span>
            {hint ? <span className="text-xs text-muted">{hint}</span> : null}
        </div>
    )
}

/**
 * Everything known about the selected intent group. Lives beside the list rather than
 * below it, so a click is always visible, and its header stays pinned while the
 * sections scroll — the selected label is the only thing tying the two panes together.
 */
export function ClusterDetailPanel(): JSX.Element {
    const { selectedCluster, clusters, categoriesByTool } = useValues(mcpClusteringLogic)

    if (!selectedCluster) {
        return (
            <div className="flex h-full items-center justify-center rounded border border-primary bg-surface-primary p-6 text-center text-sm text-muted">
                {clusters.length === 0
                    ? 'No intent groups in this snapshot yet.'
                    : 'Pick an intent group to see the goals behind it and the tools it routes to.'}
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <ClusterDetailHeader
                cluster={selectedCluster}
                categories={clusterCategories(selectedCluster, categoriesByTool)}
            />
            <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-4 p-4" data-quill>
                <IntentsSection cluster={selectedCluster} />
                <RoutingSection cluster={selectedCluster} />
                <RecoverySection cluster={selectedCluster} />
                <section className="flex flex-col gap-2">
                    <SectionLabel>Agent journeys</SectionLabel>
                    <ClusterJourneySankey journey={selectedCluster.journey ?? null} />
                </section>
            </div>
        </div>
    )
}

function ClusterDetailHeader({
    cluster,
    categories,
}: {
    cluster: MCPIntentClusterApi
    categories: string[]
}): JSX.Element {
    const worstTool = [...cluster.tool_distribution].sort((a, b) => b.error_rate_pct - a.error_rate_pct)[0]

    return (
        <header className="shrink-0 flex flex-col gap-2 border-b border-primary p-4" data-quill>
            <div className="flex flex-col gap-1">
                <span className="text-xs uppercase text-muted font-medium">Selected intent group</span>
                <h3 className="text-lg font-semibold leading-tight m-0">{cluster.label}</h3>
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
            <div className="flex flex-wrap items-center gap-2">
                <EntropyBadge entropy={cluster.routing_entropy} />
                <Badge variant={cluster.error_rate_pct > 5 ? 'destructive' : 'default'}>
                    {cluster.error_rate_pct.toFixed(1)}% errors
                </Badge>
                <Badge variant="default">{humanFriendlyNumber(cluster.call_count)} calls</Badge>
                <Badge variant="default">
                    {cluster.session_count} session{cluster.session_count === 1 ? '' : 's'}
                </Badge>
                <Badge variant="default">
                    {cluster.intent_count} intent{cluster.intent_count === 1 ? '' : 's'}
                </Badge>
            </div>
            {worstTool && worstTool.error_rate_pct > 0 ? (
                <div className="flex items-center gap-1 text-xs text-muted">
                    <IconWarning className="text-danger" />
                    Weakest tool here: <span className="font-mono">{worstTool.tool}</span>
                    <span className="text-danger ml-1">{worstTool.error_rate_pct.toFixed(1)}% errors</span>
                </div>
            ) : null}
        </header>
    )
}

function IntentsSection({ cluster }: { cluster: MCPIntentClusterApi }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <SectionLabel>What agents said they were doing</SectionLabel>
            {cluster.sample_intents.length === 0 ? (
                <div className="text-sm text-muted">No representative intents recorded.</div>
            ) : (
                <div className="flex flex-col gap-2">
                    {cluster.sample_intents.map((intent, idx) => (
                        <div key={idx} className="bg-surface-secondary rounded p-2 text-xs font-mono leading-relaxed">
                            &ldquo;{intent}&rdquo;
                        </div>
                    ))}
                </div>
            )}
        </section>
    )
}

function RoutingSection({ cluster }: { cluster: MCPIntentClusterApi }): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            <SectionLabel>Tools this goal routes to</SectionLabel>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Tool</TableHead>
                        <TableHead align="right">Calls</TableHead>
                        <TableHead>Share</TableHead>
                        <TableHead align="right">Errors</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {cluster.tool_distribution.map((row) => (
                        <TableRow key={row.tool}>
                            <TableCell expand>
                                <span className="font-mono">{row.tool}</span>
                            </TableCell>
                            <TableCell align="right">{humanFriendlyNumber(row.count)}</TableCell>
                            <TableCell>
                                <div className="flex min-w-[120px] items-center gap-2">
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
        </section>
    )
}

/**
 * What agents did after an error. Both lists are capped by the backend, so they read
 * as "at least this many" rather than a total.
 *
 * Snapshots stored before these fields existed carry neither, so both are treated as
 * absent rather than empty — the schema marks them required, the stored JSONB doesn't.
 */
function RecoverySection({ cluster }: { cluster: MCPIntentClusterApi }): JSX.Element | null {
    const switches = cluster.switches ?? []
    const selfRetries = cluster.self_retries ?? []
    if (switches.length === 0 && selfRetries.length === 0) {
        return null
    }

    return (
        <section className="flex flex-col gap-2">
            <SectionLabel hint="Counts are the strongest cases the run kept, not every occurrence.">
                What agents did after an error
            </SectionLabel>
            {switches.length > 0 ? (
                <div className="flex flex-col gap-1">
                    <Tooltip title="An errored call followed immediately by a different tool for the same goal. The clearest sign agents mix these tools up.">
                        <span className="text-xs text-muted cursor-help w-fit">Gave up and switched tool</span>
                    </Tooltip>
                    <div className="flex flex-wrap gap-1">
                        {switches.map((sw, idx) => (
                            <span
                                key={idx}
                                className="flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-xs"
                            >
                                <span className="font-mono">{sw.from_tool}</span>
                                <IconArrowRight className="text-muted" />
                                <span className="font-mono">{sw.to_tool}</span>
                                <span className="text-muted tabular-nums">×{sw.count}</span>
                            </span>
                        ))}
                    </div>
                </div>
            ) : null}
            {selfRetries.length > 0 ? (
                <div className="flex flex-col gap-1">
                    <Tooltip title="An errored call retried immediately with the same tool, which suggests the error message didn't tell the agent how to fix the call.">
                        <span className="text-xs text-muted cursor-help w-fit">Retried the same tool</span>
                    </Tooltip>
                    <div className="flex flex-wrap gap-1">
                        {selfRetries.map((retry, idx) => (
                            <span
                                key={idx}
                                className="flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-xs"
                            >
                                <IconRefresh className="text-muted" />
                                <span className="font-mono">{retry.tool}</span>
                                <span className="text-muted tabular-nums">×{retry.count}</span>
                            </span>
                        ))}
                    </div>
                </div>
            ) : null}
        </section>
    )
}
