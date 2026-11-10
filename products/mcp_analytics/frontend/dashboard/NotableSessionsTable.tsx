import { useValues } from 'kea'
import { router } from 'kea-router'

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
    cn,
} from '@posthog/quill-primitives'

import { formatPercentage } from 'lib/utils/numbers'

import { type NotableSession } from '../mcpDashboardOverviewLogic'
import { mcpSessionUrl, mcpSessionsUrl } from '../sessionUrls'
import { CardError } from './Card'
import { DESTRUCTIVE_ERROR_RATE_PCT, formatDuration, truncateSessionId } from './formatters'
import { SkeletonLine } from './SkeletonLine'

const WARNING_ERROR_PCT = 1
const SKELETON_REASON_WIDTHS = ['60%', '80%', '40%']

function statusVariant(errorRatePct: number): 'destructive' | 'warning' | 'success' {
    if (errorRatePct >= DESTRUCTIVE_ERROR_RATE_PCT) {
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

function SessionRows({
    sessions,
    loading,
    failed,
    onRetry,
    searchParams,
}: {
    sessions: NotableSession[]
    loading: boolean
    failed?: boolean
    onRetry?: () => void
    searchParams: Record<string, any>
}): JSX.Element {
    if (failed) {
        return (
            <TableEmpty className="py-6">
                <CardError onRetry={onRetry} />
            </TableEmpty>
        )
    }
    if (loading && sessions.length === 0) {
        return (
            <TableBody aria-busy>
                {SKELETON_REASON_WIDTHS.map((reasonWidth, i) => (
                    <TableRow key={i}>
                        <TableCell>
                            <SkeletonLine className="w-[65px]" />
                        </TableCell>
                        <TableCell align="right">
                            <SkeletonLine className="ml-auto w-6" />
                        </TableCell>
                        <TableCell align="right">
                            <SkeletonLine className="ml-auto w-12" />
                        </TableCell>
                        <TableCell>
                            {/* Inline like the status badge, so it sits on the text baseline and sets the same row height. */}
                            <Skeleton className="inline-flex h-4 w-[70px] items-center rounded-full py-0.5 text-[10px]">
                                <span>&nbsp;</span>
                            </Skeleton>
                        </TableCell>
                        <TableCell expand>
                            <SkeletonLine style={{ width: reasonWidth }} />
                        </TableCell>
                    </TableRow>
                ))}
            </TableBody>
        )
    }
    if (sessions.length === 0) {
        return (
            <TableEmpty className="py-6 text-secondary">
                No sessions were flagged in this date range. Try a wider range.
            </TableEmpty>
        )
    }
    return (
        <TableBody aria-busy={loading} className={cn('transition-opacity', loading && 'opacity-50')}>
            {sessions.map((entry) => (
                <TableRow key={entry.session.session_id}>
                    <TableCell className="whitespace-nowrap">
                        <Link
                            to={mcpSessionUrl(entry.session.session_id, searchParams)}
                            className="font-mono"
                            title={entry.session.session_id}
                        >
                            {truncateSessionId(entry.session.session_id)}
                        </Link>
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {entry.session.tool_calls}
                    </TableCell>
                    <TableCell align="right" className="tabular-nums">
                        {formatDuration(entry.session.duration_seconds)}
                    </TableCell>
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
    failed,
    onRetry,
}: {
    sessions: NotableSession[]
    loading: boolean
    failed?: boolean
    onRetry?: () => void
}): JSX.Element {
    const { searchParams } = useValues(router)
    return (
        <Card size="sm" className="gap-0 self-start">
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
                <SessionRows
                    sessions={sessions}
                    loading={loading}
                    failed={failed}
                    onRetry={onRetry}
                    searchParams={searchParams}
                />
            </Table>
            <CardFooter className="justify-end">
                <Link to={mcpSessionsUrl(searchParams)} className="text-xs">
                    Open in Sessions tab
                </Link>
            </CardFooter>
        </Card>
    )
}
