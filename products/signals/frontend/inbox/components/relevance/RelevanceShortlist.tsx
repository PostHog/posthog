import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'
import { CardSkeleton } from '../cards/CardSkeleton'
import { RelevanceShortlistCard } from './RelevanceShortlistCard'

export interface RelevanceShortlistProps {
    reports: SignalReport[]
    loading: boolean
    failed: boolean
    saving: boolean
    lastSnoozed: SignalReport | null
    onRetry: () => void
    onShowQueue: () => void
    onSnooze: (report: SignalReport, snoozed: boolean) => void
}

export function RelevanceShortlist({
    reports,
    loading,
    failed,
    saving,
    lastSnoozed,
    onRetry,
    onShowQueue,
    onSnooze,
}: RelevanceShortlistProps): JSX.Element {
    return (
        <div className="mx-auto max-w-4xl p-4 space-y-4" data-attr="inbox-relevance-shortlist">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="mb-1">For you</h2>
                    <p className="text-secondary mb-0">Up to five reports that need attention.</p>
                </div>
                <LemonButton type="secondary" onClick={onShowQueue} data-attr="inbox-shortlist-wider-queue">
                    Browse all reports
                </LemonButton>
            </div>
            <p className="text-secondary text-sm">
                Suggested to you, P0–P2, highest priority first. Reports already being handled stay in the wider queue.
            </p>
            {lastSnoozed && (
                <LemonBanner
                    type="info"
                    action={{ children: 'Undo', onClick: () => onSnooze(lastSnoozed, false), loading: saving }}
                >
                    Hidden from your shortlist for seven days. Everyone else can still see it.
                </LemonBanner>
            )}
            {failed ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry }}>
                    Could not load your shortlist.
                </LemonBanner>
            ) : loading ? (
                <CardSkeleton count={3} variant="cards" />
            ) : reports.length ? (
                <div className="space-y-3">
                    {reports.map((report) => (
                        <RelevanceShortlistCard
                            key={report.id}
                            report={report}
                            saving={saving}
                            onSnooze={() => onSnooze(report, true)}
                        />
                    ))}
                </div>
            ) : (
                <LemonBanner type="info">
                    Nothing needs your attention here right now. You can still browse all reports, including
                    lower-priority and snoozed reports.
                </LemonBanner>
            )}
        </div>
    )
}
