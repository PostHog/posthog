import { useValues } from 'kea'

import { Badge, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { formatErrorRate } from './clusterRanking'
import { mcpClusteringLogic } from './mcpClusteringLogic'

/**
 * Intent texts that open several sessions word for word, such as scheduled agents and cron
 * runs. They are kept out of the groups above so one busy automation can't pose as a theme.
 */
export function RecurringIntentsSection(): JSX.Element | null {
    const { recurring, toolsInScope } = useValues(mcpClusteringLogic)

    // Recurring rows carry no tool breakdown, so they can't be narrowed to a category.
    if (recurring.length === 0 || toolsInScope) {
        return null
    }

    return (
        <section
            className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-3"
            data-attr="mcp-clustering-recurring"
        >
            <div className="flex flex-col">
                <h3 className="text-sm font-semibold m-0">Recurring automated intents</h3>
                <span className="text-xs text-muted">
                    The same intent text opened 3 or more sessions, which usually means a scheduled agent or script.
                    These are listed here instead of in the intent groups.
                </span>
            </div>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Intent</TableHead>
                        <TableHead align="right">Sessions</TableHead>
                        <TableHead align="right">Calls</TableHead>
                        <TableHead align="right">Error rate</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {recurring.map((row, index) => (
                        <TableRow key={`${index}-${row.intent_text}`}>
                            <TableCell expand>
                                <span className="line-clamp-2 font-mono text-xs" title={row.intent_text}>
                                    {row.intent_text.trim() || `Recurring intent ${index + 1}`}
                                </span>
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                {humanFriendlyNumber(row.session_count)}
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                {humanFriendlyNumber(row.call_count)}
                            </TableCell>
                            <TableCell align="right" className="tabular-nums">
                                {row.error_count > 0 ? (
                                    <Badge variant="destructive">{formatErrorRate(row.error_rate_pct)}</Badge>
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
