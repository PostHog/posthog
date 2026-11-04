import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { EmailMetricsIncidentBanner } from '../EmailMetricsIncidentBanner'
import { EmailLinksTable } from '../Workflows/EmailLinksTable'
import { BroadcastPerformanceLogicProps, broadcastPerformanceLogic } from './broadcastPerformanceLogic'
import { BroadcastSendActivity } from './BroadcastSendActivity'
import { BroadcastSendErrorAction, BroadcastSendErrorBanner } from './BroadcastSendErrorBanner'

function share(part: number, whole: number): string {
    return whole > 0 ? percentage(part / whole, 1) : '-'
}

export function BroadcastPerformance({
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
    const { stats, sendCounts, trackingOff, totalsLoading, totalsFailed, links, linksLoading } = useValues(logic)
    const { loadTotals } = useActions(logic)

    const showLinks = !!stats && stats.sent > 0 && !trackingOff

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

    const notSent = sendCounts?.notSent ?? 0
    const headline = [
        { label: 'Sent', value: humanFriendlyNumber(stats.sent), detail: null },
        ...(notSent > 0 ? [{ label: 'Not sent', value: humanFriendlyNumber(notSent), detail: null }] : []),
        { label: 'Delivered', value: share(stats.delivered, stats.sent), detail: stats.delivered },
        { label: 'Bounced', value: share(stats.bounced, stats.sent), detail: stats.bounced },
        { label: 'Marked as spam', value: share(stats.markedAsSpam, stats.sent), detail: stats.markedAsSpam },
        { label: 'Failed', value: share(stats.failed, stats.sent), detail: stats.failed },
        { label: 'Unsubscribed', value: share(stats.unsubscribed, stats.sent), detail: stats.unsubscribed },
    ]
    const engagement = [
        ...(trackingOff
            ? []
            : [
                  { label: 'Opened', part: stats.opened, whole: stats.trackedSends },
                  { label: 'Clicked', part: stats.clicked, whole: stats.trackedSends },
                  { label: 'Clicked to opened', part: stats.clicked, whole: stats.opened },
              ]),
        ...(hasGoal ? [{ label: 'Converted', part: stats.converted, whole: stats.sent }] : []),
    ]
    const footnote = [
        trackingOff ? null : 'Opens and clicks are counted against sends with tracking on.',
        hasGoal ? 'Conversions are counted against all sends.' : null,
    ]
        .filter(Boolean)
        .join(' ')

    return (
        <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface-primary p-4">
            <EmailMetricsIncidentBanner dateFrom={dayjs(props.runStartedAt)} />
            <BroadcastSendErrorBanner {...props} fixAction={fixAction} resendAction={resendAction} content={content} />
            <div
                className={cn(
                    'grid grid-cols-2 gap-4',
                    notSent > 0 ? '@xl:grid-cols-4 @4xl:grid-cols-7' : '@xl:grid-cols-3 @4xl:grid-cols-6'
                )}
            >
                {headline.map(({ label, value, detail }) => (
                    <div key={label} className="flex flex-col">
                        <span className="text-xl font-semibold">{value}</span>
                        <span className="text-xs uppercase tracking-wide text-muted">
                            {detail === null ? label : `${humanFriendlyNumber(detail)} ${label.toLowerCase()}`}
                        </span>
                    </div>
                ))}
            </div>

            {stats.sent > 0 && trackingOff ? (
                <LemonBanner type="info">
                    Open and click tracking was off for this send, so opens and clicks weren't recorded. Before the next
                    send, check the tracking setting on the email and the email tracking consent setting in your
                    environment settings.
                </LemonBanner>
            ) : null}

            {/* With nothing sent there is nothing to engage with, so empty bars and charts would only add noise. */}
            {stats.sent > 0 ? (
                <div className="flex flex-col gap-3">
                    {engagement.map(({ label, part, whole }) => (
                        <div key={label} className="grid grid-cols-[9rem_minmax(0,1fr)] items-center gap-3">
                            <div className="flex flex-col text-right">
                                <span className="font-semibold">{share(part, whole)}</span>
                                <span className="text-xs text-muted">
                                    {humanFriendlyNumber(part)} {label.toLowerCase()}
                                </span>
                            </div>
                            <LemonProgress percent={whole > 0 ? (part / whole) * 100 : 0} size="large" />
                        </div>
                    ))}
                    {footnote ? <span className="text-xs text-muted">{footnote}</span> : null}
                </div>
            ) : null}

            {stats.sent > 0 ? <BroadcastSendActivity {...props} /> : null}

            {showLinks ? (
                <div className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Top clicked links</h3>
                    <EmailLinksTable links={links} loading={linksLoading} emptyState="No link clicks yet" />
                </div>
            ) : null}
        </div>
    )
}
