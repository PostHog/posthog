import { useValues } from 'kea'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { transactionalEmailPerformanceLogic } from './transactionalEmailPerformanceLogic'

export function TransactionalEmailResultsStats(): JSX.Element {
    const { resultsQuery, results, resultsLoading } = useValues(transactionalEmailPerformanceLogic)

    return (
        <div
            className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(12rem,1fr))]"
            data-attr="transactional-email-results-stats"
        >
            <AnalyticsMetricCard
                title="People sent the email"
                loading={resultsLoading || !results}
                value={results?.recipients}
                formatValue={(value: number) => humanFriendlyNumber(value)}
                subtitle="First send per person"
            />
            <AnalyticsMetricCard
                title={`Did ${resultsQuery.event} after`}
                loading={resultsLoading || !results}
                value={results?.converted}
                formatValue={(value: number) => humanFriendlyNumber(value)}
                subtitle={
                    results ? `${percentage(results.converted / results.recipients, 1, true)} of them` : undefined
                }
            />
            <AnalyticsMetricCard
                title="Median time to convert"
                loading={resultsLoading || !results}
                value={results?.median_hours_to_convert ?? undefined}
                formatValue={(hours: number) => humanFriendlyDuration(hours * 3600, { maxUnits: 2 })}
                subtitle="From the send to the event"
                emptyMessage="Nobody converted yet"
            />
            {resultsQuery.revenueProperty && (
                <AnalyticsMetricCard
                    title="Revenue"
                    loading={resultsLoading || !results}
                    value={results?.revenue}
                    formatValue={(value: number) => humanFriendlyNumber(value, 2)}
                    subtitle={`From ${resultsQuery.revenueProperty}`}
                />
            )}
        </div>
    )
}
