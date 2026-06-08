import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { Badge, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { urls } from 'scenes/urls'

import { type NotableSession } from '../mcpDashboardOverviewLogic'
import { formatDuration, formatPercent, truncateSessionId } from './formatters'

function StatusPill({ errorRatePct }: { errorRatePct: number }): JSX.Element {
    if (errorRatePct === 0) {
        return <Badge variant="success">Healthy</Badge>
    }
    const variant = errorRatePct > 5 ? 'destructive' : errorRatePct >= 1 ? 'warning' : 'success'
    return <Badge variant={variant}>{formatPercent(errorRatePct)} errors</Badge>
}

export function NotableSessionsTable({
    sessions,
    loading,
}: {
    sessions: NotableSession[]
    loading: boolean
}): JSX.Element {
    return (
        <div className="flex h-full flex-col overflow-hidden rounded-lg border border-primary bg-surface-primary">
            <h3 className="mb-0 border-b border-primary px-3.5 py-3 text-sm font-medium text-primary">
                Sessions flagged for review
            </h3>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead>Session</TableHead>
                        <TableHead align="right">Calls</TableHead>
                        <TableHead align="right">Duration</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead expand>Why notable</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {loading && sessions.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={5}>
                                <div className="space-y-2 py-1">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                                    ))}
                                </div>
                            </TableCell>
                        </TableRow>
                    ) : sessions.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={5} align="center" className="py-6 text-secondary">
                                No notable sessions in the last 30 days.
                            </TableCell>
                        </TableRow>
                    ) : (
                        sessions.map((entry) => (
                            <TableRow key={entry.session.session_id}>
                                <TableCell className="whitespace-nowrap">
                                    <Link
                                        to={urls.mcpAnalyticsSessions()}
                                        className="font-mono"
                                        title={entry.session.session_id}
                                    >
                                        {truncateSessionId(entry.session.session_id)}
                                    </Link>
                                </TableCell>
                                <TableCell align="right">{entry.session.tool_calls}</TableCell>
                                <TableCell align="right">{formatDuration(entry.session.duration_seconds)}</TableCell>
                                <TableCell>
                                    <StatusPill errorRatePct={entry.session.error_rate_pct} />
                                </TableCell>
                                <TableCell expand className="text-primary" title={entry.label}>
                                    {entry.label}
                                </TableCell>
                            </TableRow>
                        ))
                    )}
                </TableBody>
            </Table>
            {sessions.length > 0 && (
                <div className="mt-auto flex justify-end border-t border-primary px-3.5 py-2">
                    <Link to={urls.mcpAnalyticsSessions()} className="text-[10px]">
                        Open all flagged sessions in Sessions tab ↗
                    </Link>
                </div>
            )}
        </div>
    )
}
