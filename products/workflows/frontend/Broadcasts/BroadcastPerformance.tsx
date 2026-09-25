import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { EmailLinksTable } from '../Workflows/EmailLinksTable'
import { BroadcastPerformanceLogicProps, broadcastPerformanceLogic } from './broadcastPerformanceLogic'

function share(part: number, whole: number): string {
    return whole > 0 ? percentage(part / whole, 1) : '-'
}

export function BroadcastPerformance(props: BroadcastPerformanceLogicProps): JSX.Element {
    const { stats, totalsLoading, links, linksLoading } = useValues(broadcastPerformanceLogic(props))

    if (!stats) {
        return <LemonSkeleton className="h-40" active={totalsLoading} />
    }

    const headline = [
        { label: 'Sent', value: humanFriendlyNumber(stats.sent), detail: null },
        { label: 'Delivered', value: share(stats.delivered, stats.sent), detail: stats.delivered },
        { label: 'Bounced', value: share(stats.bounced, stats.sent), detail: stats.bounced },
        { label: 'Marked as spam', value: share(stats.markedAsSpam, stats.sent), detail: stats.markedAsSpam },
        { label: 'Failed', value: share(stats.failed, stats.sent), detail: stats.failed },
    ]
    const engagement = [
        { label: 'Opened', part: stats.opened, whole: stats.trackedSends },
        { label: 'Clicked', part: stats.clicked, whole: stats.trackedSends },
        { label: 'Clicked to opened', part: stats.clicked, whole: stats.opened },
    ]

    return (
        <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface-primary p-4">
            <div className="grid grid-cols-2 gap-4 @xl:grid-cols-5">
                {headline.map(({ label, value, detail }) => (
                    <div key={label} className="flex flex-col">
                        <span className="text-xl font-semibold">{value}</span>
                        <span className="text-xs uppercase tracking-wide text-muted">
                            {detail === null ? label : `${humanFriendlyNumber(detail)} ${label.toLowerCase()}`}
                        </span>
                    </div>
                ))}
            </div>

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
                <span className="text-xs text-muted">Opens and clicks are counted against sends with tracking on.</span>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="m-0 text-sm font-semibold">Top clicked links</h3>
                <EmailLinksTable links={links} loading={linksLoading} emptyState="No link clicks yet" />
            </div>
        </div>
    )
}
