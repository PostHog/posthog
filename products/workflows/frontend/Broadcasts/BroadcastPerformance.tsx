import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { EmailLinksTable } from '../Workflows/EmailLinksTable'
import {
    BroadcastEmailSkips,
    BroadcastPerformanceLogicProps,
    BroadcastPerformanceStats,
    broadcastPerformanceLogic,
} from './broadcastPerformanceLogic'
import { BroadcastSendActivity } from './BroadcastSendActivity'

function share(part: number, whole: number): string {
    return whole > 0 ? percentage(part / whole, 1) : '-'
}

const EMAIL_SKIP_LABELS: Record<keyof BroadcastEmailSkips, string> = {
    frequencyCapped: 'already got the most marketing messages your frequency cap allows',
    missingRecipient: 'have no email address',
    bouncePrevented: 'have an address that would bounce',
    suppressed: 'are on the suppression list',
    suspended: 'were skipped because email sending is suspended for this project',
    paused: 'were skipped because sending is paused for this broadcast',
}

function SkippedEmailsBanner({ stats }: { stats: BroadcastPerformanceStats }): JSX.Element | null {
    const reasons = (Object.keys(EMAIL_SKIP_LABELS) as (keyof BroadcastEmailSkips)[]).filter(
        (reason) => stats.emailSkips[reason] > 0
    )
    if (reasons.length === 0) {
        return null
    }
    const skipped = reasons.reduce((total, reason) => total + stats.emailSkips[reason], 0)
    return (
        <LemonBanner type={stats.sent === 0 ? 'warning' : 'info'}>
            <p className="mb-1">
                {stats.sent === 0
                    ? `No emails went out. All ${humanFriendlyNumber(skipped)} sends were skipped:`
                    : `${humanFriendlyNumber(skipped)} sends were skipped:`}
            </p>
            <ul className="list-disc pl-4 mb-0">
                {reasons.map((reason) => (
                    <li key={reason}>
                        {humanFriendlyNumber(stats.emailSkips[reason])} {EMAIL_SKIP_LABELS[reason]}
                        {reason === 'frequencyCapped' ? (
                            <>
                                {'. '}
                                <Link
                                    to={urls.settings('environment-workflows', 'workflows-frequency-cap')}
                                    data-attr="broadcast-skipped-frequency-cap-settings"
                                >
                                    Change the frequency cap
                                </Link>
                            </>
                        ) : null}
                    </li>
                ))}
            </ul>
        </LemonBanner>
    )
}

export function BroadcastPerformance({
    hasGoal = false,
    ...props
}: BroadcastPerformanceLogicProps & { hasGoal?: boolean }): JSX.Element {
    const logic = broadcastPerformanceLogic(props)
    const { stats, trackingOff, totalsLoading, totalsFailed, links, linksLoading } = useValues(logic)
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

    const headline = [
        { label: 'Sent', value: humanFriendlyNumber(stats.sent), detail: null },
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
            <div className="grid grid-cols-2 gap-4 @xl:grid-cols-3 @4xl:grid-cols-6">
                {headline.map(({ label, value, detail }) => (
                    <div key={label} className="flex flex-col">
                        <span className="text-xl font-semibold">{value}</span>
                        <span className="text-xs uppercase tracking-wide text-muted">
                            {detail === null ? label : `${humanFriendlyNumber(detail)} ${label.toLowerCase()}`}
                        </span>
                    </div>
                ))}
            </div>

            <SkippedEmailsBanner stats={stats} />

            {trackingOff ? (
                <LemonBanner type="info">
                    Open and click tracking was off for this send, so opens and clicks weren't recorded. Before the next
                    send, check the tracking setting on the email and the email tracking consent setting in your
                    environment settings.
                </LemonBanner>
            ) : null}

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

            <BroadcastSendActivity {...props} />

            {trackingOff ? null : (
                <div className="flex flex-col gap-2">
                    <h3 className="m-0 text-sm font-semibold">Top clicked links</h3>
                    <EmailLinksTable links={links} loading={linksLoading} emptyState="No link clicks yet" />
                </div>
            )}
        </div>
    )
}
