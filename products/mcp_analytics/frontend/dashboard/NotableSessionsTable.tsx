import { Link } from '@posthog/lemon-ui'
import {
    Badge,
    Card,
    CardFooter,
    CardHeader,
    CardTitle,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
} from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { type NotableSession } from '../mcpDashboardOverviewLogic'
import { formatDuration, truncateSessionId } from './formatters'

const DESTRUCTIVE_ERROR_PCT = 5
const WARNING_ERROR_PCT = 1

function statusVariant(errorRatePct: number): 'destructive' | 'warning' | 'success' {
    if (errorRatePct > DESTRUCTIVE_ERROR_PCT) {
        return 'destructive'
    }
    if (errorRatePct >= WARNING_ERROR_PCT) {
        return 'warning'
    }
    return 'success'
}

function StatusPill({ errorRatePct }: { errorRatePct: number }): JSX.Element {
    if (errorRatePct === 0) {
        return <Badge variant="success">Healthy</Badge>
    }
    return (
        <Badge variant={statusVariant(errorRatePct)}>{formatPercentage(errorRatePct, { compact: true })} errors</Badge>
    )
}

function SessionRows({ sessions, loading }: { sessions: NotableSession[]; loading: boolean }): JSX.Element {
    if (loading && sessions.length === 0) {
        return (
            <TableBody>
                <TableRow>
                    <TableCell colSpan={5}>
                        <div className="space-y-2 py-1">
                            {Array.from({ length: 4 }).map((_, i) => (
                                <Skeleton key={i} className="h-3.5 w-full" />
                            ))}
                        </div>
                    </TableCell>
                </TableRow>
            </TableBody>
        )
    }
    if (sessions.length === 0) {
        return <TableEmpty className="py-6 text-secondary">No notable sessions in the last 30 days.</TableEmpty>
    }
    return (
        <TableBody>
            {sessions.map((entry) => (
                <TableRow key={entry.session.session_id}>
                    <TableCell className="whitespace-nowrap">
                        <Link to={urls.mcpAnalyticsSessions()} className="font-mono" title={entry.session.session_id}>
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
            ))}
        </TableBody>
    )
}

export function NotableSessionsTable({
    sessions,
    loading,
}: {
    sessions: NotableSession[]
    loading: boolean
}): JSX.Element {
    return (
        <Card size="sm" className="gap-0">
            <CardHeader className="border-b border-border pb-3">
                <CardTitle>Sessions flagged for review</CardTitle>
            </CardHeader>
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
                <SessionRows sessions={sessions} loading={loading} />
            </Table>
            {sessions.length > 0 && (
                <CardFooter className="justify-end">
                    <Link to={urls.mcpAnalyticsSessions()} className="text-[10px]">
                        Open all flagged sessions in Sessions tab ↗
                    </Link>
                </CardFooter>
            )}
        </Card>
    )
}
