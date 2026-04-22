import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { compactNumber } from 'lib/utils'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

export function SummaryStats(): JSX.Element {
    const { summaryStats, summaryStatsLoading } = useValues(errorTrackingInsightsLogic)

    const cards = [
        { label: 'Total exceptions', value: summaryStats ? compactNumber(summaryStats.totalExceptions) : null },
        { label: 'Affected users', value: summaryStats ? compactNumber(summaryStats.affectedUsers) : null },
        { label: 'Total sessions', value: summaryStats ? compactNumber(summaryStats.totalSessions) : null },
        { label: 'Sessions with crash', value: summaryStats ? compactNumber(summaryStats.crashSessions) : null },
        { label: 'Crash-free sessions', value: summaryStats ? `${summaryStats.crashFreeRate}%` : null },
    ]

    return (
        <div className="grid grid-cols-2 xl:grid-cols-5 gap-4">
            {cards.map(({ label, value }) => (
                <div key={label} className="border rounded-lg bg-surface-primary p-4 flex flex-col gap-1">
                    <span className="text-xs text-secondary">{label}</span>
                    {summaryStatsLoading ? (
                        <LemonSkeleton className="h-8 w-20" />
                    ) : (
                        <span className="text-2xl font-bold">{value ?? '—'}</span>
                    )}
                </div>
            ))}
        </div>
    )
}
