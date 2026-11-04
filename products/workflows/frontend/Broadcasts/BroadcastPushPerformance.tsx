import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { BroadcastPerformanceLogicProps, broadcastPerformanceLogic } from './broadcastPerformanceLogic'
import { BroadcastSendActivity } from './BroadcastSendActivity'
import { BroadcastSendErrorAction, BroadcastSendErrorBanner } from './BroadcastSendErrorBanner'

const PUSH_DOCS_URL = 'https://posthog.com/docs/workflows/push-notifications'

// Keyed by how many stats show, since the goal and the not sent stats only show when they apply.
const STAT_GRID_COLUMNS: Record<number, string> = {
    4: '@xl:grid-cols-4',
    5: '@xl:grid-cols-5',
    6: '@xl:grid-cols-3 @4xl:grid-cols-6',
}

function ofSent(part: number, sent: number): string {
    return sent > 0 ? `${percentage(part / sent, 1)} of sent` : 'of sent'
}

function Stat({
    label,
    value,
    detail,
    info,
}: {
    label: string
    value: number
    detail: string
    info?: string
}): JSX.Element {
    return (
        <div className="flex flex-col" data-attr={`broadcast-push-stat-${label.toLowerCase().replace(' ', '-')}`}>
            <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
            <span className="text-xl font-semibold">{humanFriendlyNumber(value)}</span>
            <span className="flex items-center gap-1 text-xs text-muted">
                {detail}
                {info ? (
                    <Tooltip title={info}>
                        <IconInfo className="text-sm" />
                    </Tooltip>
                ) : null}
            </span>
        </div>
    )
}

/** A push send's numbers. Push providers confirm they accepted a notification, never that a phone showed it. */
export function BroadcastPushPerformance({
    hasGoal = false,
    fixAction,
    resendAction,
    content,
    ...props
}: BroadcastPerformanceLogicProps & {
    hasGoal?: boolean
    fixAction?: BroadcastSendErrorAction
    resendAction?: BroadcastSendErrorAction
    content?: string
}): JSX.Element {
    const logic = broadcastPerformanceLogic(props)
    const { stats, sendCounts, totalsLoading, totalsFailed } = useValues(logic)
    const { loadTotals } = useActions(logic)

    if (totalsFailed && !totalsLoading) {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadTotals, 'data-attr': 'broadcast-performance-retry' }}
            >
                Couldn't load this send's numbers.
            </LemonBanner>
        )
    }
    if (!stats) {
        return <LemonSkeleton className="h-40" active={totalsLoading} />
    }

    const attempted = stats.sent + stats.skipped + stats.failed
    const notSent = sendCounts?.notSent ?? 0
    const statCount = 4 + (hasGoal ? 1 : 0) + (notSent > 0 ? 1 : 0)

    return (
        <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface-primary p-4">
            <BroadcastSendErrorBanner {...props} fixAction={fixAction} resendAction={resendAction} content={content} />
            <div className={cn('grid grid-cols-2 gap-4', STAT_GRID_COLUMNS[statCount])}>
                <Stat
                    label="Sent"
                    value={stats.sent}
                    detail={`of ${humanFriendlyNumber(attempted)} attempted`}
                    info="Accepted by Apple or Google. They don't confirm the phone received it."
                />
                {notSent > 0 ? <Stat label="Not sent" value={notSent} detail="people, stopped by an error" /> : null}
                <Stat label="Opened" value={stats.opened} detail={ofSent(stats.opened, stats.sent)} />
                <Stat
                    label="No device"
                    value={stats.skipped}
                    detail="no registered phone"
                    info="These people haven't registered a phone for this app yet, for example they never allowed notifications, turned them off, or reinstalled the app."
                />
                <Stat label="Failed" value={stats.failed} detail="errors" />
                {hasGoal ? (
                    <Stat label="Converted" value={stats.converted} detail={ofSent(stats.converted, stats.sent)} />
                ) : null}
            </div>
            <span className="text-xs text-muted">
                Counts are notifications, one for each app a person is sent through. Opens are counted when your app
                reports a tapped notification. Your app registers each phone for push,{' '}
                <Link to={PUSH_DOCS_URL} target="_blank">
                    see the push setup guide
                </Link>
                .
            </span>
            {stats.sent > 0 ? <BroadcastSendActivity {...props} hideSingleBucket /> : null}
        </div>
    )
}
