import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'
import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPToolPivotApi } from '../generated/api.schemas'
import { ContestedBadge } from './EntropyBadge'
import { ToolSortKey, mcpClusteringLogic, weightedMeanFit } from './mcpClusteringLogic'

const SORT_LABELS: Record<ToolSortKey, string> = {
    calls: 'Calls',
    contested: 'Contested',
    discovery: 'Discovery rate',
}

function DiscoveryCell({ tool }: { tool: MCPToolPivotApi }): JSX.Element {
    if (tool.discovery_rate_pct === null) {
        return (
            <Tooltip
                title={
                    tool.advertised_sessions === 0
                        ? 'No sampled session with a tools-list catalog advertised this tool, so there is no denominator to measure discovery against.'
                        : `Advertised in only ${tool.advertised_sessions} sampled session${tool.advertised_sessions === 1 ? '' : 's'}, which is not enough to measure a rate.`
                }
            >
                <span className="text-muted cursor-help">—</span>
            </Tooltip>
        )
    }
    return (
        <Tooltip
            title={`Called in ${tool.called_when_advertised} of the ${tool.advertised_sessions} sampled sessions that advertised it.`}
        >
            <span className={`tabular-nums cursor-help ${tool.discovery_rate_pct < 25 ? 'text-danger' : ''}`}>
                {tool.discovery_rate_pct.toFixed(1)}%
            </span>
        </Tooltip>
    )
}

function FitCell({ tool }: { tool: MCPToolPivotApi }): JSX.Element {
    const fit = weightedMeanFit(tool)
    if (fit === null) {
        return (
            <Tooltip title="No description has been captured for this tool yet, so its fit to the intents can't be scored.">
                <span className="text-muted cursor-help">—</span>
            </Tooltip>
        )
    }
    return (
        <Tooltip title="Call-weighted cosine similarity between the tool's description and the intents that route to it. Higher means the description matches what agents actually use the tool for.">
            <span className="tabular-nums cursor-help">{fit.toFixed(2)}</span>
        </Tooltip>
    )
}

export function ToolPivotTable(): JSX.Element {
    const { sortedTools, toolSortKey, selectedToolName } = useValues(mcpClusteringLogic)
    const { selectTool, setToolSortKey } = useActions(mcpClusteringLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-muted">Sort tools by</span>
                {(Object.keys(SORT_LABELS) as ToolSortKey[]).map((key) => (
                    <Button
                        key={key}
                        size="sm"
                        variant={toolSortKey === key ? 'default' : 'outline'}
                        onClick={() => setToolSortKey(key)}
                    >
                        {SORT_LABELS[key]}
                    </Button>
                ))}
            </div>
            <div className="bg-surface-primary border rounded" data-quill>
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Tool</TableHead>
                            <TableHead align="right">Calls</TableHead>
                            <TableHead align="right">Errors</TableHead>
                            <TableHead align="right">Intents served</TableHead>
                            <TableHead>Routing</TableHead>
                            <TableHead align="right">Discovery</TableHead>
                            <TableHead align="right">Description fit</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {sortedTools.length === 0 ? (
                            <TableRow>
                                {/* A category can name tools this snapshot never saw, so an empty
                                    table is reachable and has to say why rather than show bare headers. */}
                                <TableCell colSpan={7} className="p-4 text-center text-sm text-muted">
                                    No tools match the current category scope or search.
                                </TableCell>
                            </TableRow>
                        ) : null}
                        {sortedTools.map((tool) => (
                            <TableRow
                                key={tool.tool}
                                onClick={() => selectTool(tool.tool)}
                                data-state={selectedToolName === tool.tool ? 'selected' : undefined}
                                className={`cursor-pointer ${
                                    selectedToolName === tool.tool
                                        ? 'bg-accent-highlight-secondary'
                                        : 'hover:bg-accent-highlight-secondary'
                                }`}
                            >
                                <TableCell expand>
                                    <span className="font-mono">{tool.tool}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{humanFriendlyNumber(tool.call_count)}</span>
                                </TableCell>
                                <TableCell align="right">
                                    {tool.error_count > 0 ? (
                                        <span className="tabular-nums text-danger">
                                            {humanFriendlyNumber(tool.error_count)}
                                        </span>
                                    ) : (
                                        <span className="text-muted">0</span>
                                    )}
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{humanFriendlyNumber(tool.n_clusters_served)}</span>
                                </TableCell>
                                <TableCell>
                                    <ContestedBadge score={tool.contested_score} />
                                </TableCell>
                                <TableCell align="right">
                                    <DiscoveryCell tool={tool} />
                                </TableCell>
                                <TableCell align="right">
                                    <FitCell tool={tool} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    )
}
