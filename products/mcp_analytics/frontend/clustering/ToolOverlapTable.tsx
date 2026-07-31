import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'
import { Badge, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MCPToolOverlapApi } from '../generated/api.schemas'
import { mcpClusteringLogic } from './mcpClusteringLogic'

function RelationshipBadge({ overlap }: { overlap: MCPToolOverlapApi }): JSX.Element {
    if (overlap.sessions_with_either === 0) {
        return <span className="text-muted">—</span>
    }
    const togetherShare = overlap.sessions_with_both / overlap.sessions_with_either
    if (togetherShare >= 0.5) {
        return (
            <Tooltip
                title={`${overlap.sessions_with_both} of ${overlap.sessions_with_either} sessions used both tools, so this pair looks like a workflow rather than confusion.`}
            >
                <span>
                    <Badge variant="default">Used together</Badge>
                </span>
            </Tooltip>
        )
    }
    return (
        <Tooltip
            title={`Only ${overlap.sessions_with_both} of ${overlap.sessions_with_either} sessions used both tools. Agents usually pick one or the other for these intents, which suggests the tools compete.`}
        >
            <span>
                <Badge variant="warning">One or the other</Badge>
            </span>
        </Tooltip>
    )
}

/**
 * Tool pairs competing for the same intent clusters. This is also the pre and
 * post check for description rewrites: a rewrite that wins one intent can pull
 * traffic from the tool that should own another.
 */
export function ToolOverlapTable(): JSX.Element | null {
    const { toolOverlaps } = useValues(mcpClusteringLogic)

    if (toolOverlaps.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col">
                <span className="text-xs uppercase text-muted font-medium">Tools competing for the same intents</span>
                <span className="text-xs text-muted">
                    Contested calls is the volume both tools plausibly compete for across shared intent clusters.
                </span>
            </div>
            <div className="bg-surface-primary border rounded" data-quill>
                <Table fullWidth>
                    <TableHeader>
                        <TableRow>
                            <TableHead expand>Pair</TableHead>
                            <TableHead align="right">Contested calls</TableHead>
                            <TableHead align="right">Sessions with both</TableHead>
                            <TableHead align="right">Sessions with either</TableHead>
                            <TableHead>Relationship</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {toolOverlaps.map((overlap) => (
                            <TableRow key={`${overlap.tool_a}|${overlap.tool_b}`}>
                                <TableCell expand>
                                    <span className="font-mono">{overlap.tool_a}</span>
                                    <span className="text-muted"> + </span>
                                    <span className="font-mono">{overlap.tool_b}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{humanFriendlyNumber(overlap.contested_calls)}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{overlap.sessions_with_both}</span>
                                </TableCell>
                                <TableCell align="right">
                                    <span className="tabular-nums">{overlap.sessions_with_either}</span>
                                </TableCell>
                                <TableCell>
                                    <RelationshipBadge overlap={overlap} />
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
        </div>
    )
}
