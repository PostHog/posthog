import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { messageTemplatesLogic } from '../../TemplateLibrary/messageTemplatesLogic'
import { transactionalEmailPerformanceLogic } from './transactionalEmailPerformanceLogic'

export function TransactionalEmailResults(): JSX.Element {
    const { resultsQuery, results, resultsLoading, resultsFailed, canLoadResults } = useValues(
        transactionalEmailPerformanceLogic
    )
    const { setResultsQuery, loadResults } = useActions(transactionalEmailPerformanceLogic)
    const { transactionalTemplates } = useValues(messageTemplatesLogic)

    const emailOptions = transactionalTemplates
        .filter((template) => template.transactional_hog_flow_id)
        .map((template) => ({
            value: template.transactional_hog_flow_id as string,
            label: template.name || 'Unnamed email',
        }))

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>Of the people sent</span>
                <LemonSelect
                    size="small"
                    placeholder="Choose an email"
                    value={resultsQuery.workflowId}
                    onChange={(workflowId) => setResultsQuery({ workflowId })}
                    options={emailOptions}
                    data-attr="transactional-email-results-email"
                />
                <span>how many did</span>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.Events}
                    value={resultsQuery.event ?? undefined}
                    onChange={(event) => setResultsQuery({ event: event ? String(event) : null })}
                    placeholder="Choose an event"
                    size="small"
                    data-attr="transactional-email-results-event"
                />
                <span>within</span>
                <LemonInput
                    type="number"
                    size="small"
                    min={1}
                    max={30}
                    value={resultsQuery.windowDays}
                    onChange={(windowDays) =>
                        setResultsQuery({ windowDays: Math.min(Math.max(Math.round(windowDays ?? 1), 1), 30) })
                    }
                    className="w-16"
                    data-attr="transactional-email-results-window"
                />
                <span>days, with revenue from</span>
                <TaxonomicPopover
                    groupType={TaxonomicFilterGroupType.EventProperties}
                    value={resultsQuery.revenueProperty ?? undefined}
                    onChange={(property) => setResultsQuery({ revenueProperty: property ? String(property) : null })}
                    placeholder="No revenue property"
                    allowClear
                    size="small"
                    data-attr="transactional-email-results-revenue"
                />
            </div>
            {!canLoadResults ? (
                <p className="text-secondary text-sm m-0">
                    Choose an email and the event that counts as a conversion, such as a signup or a purchase.
                </p>
            ) : resultsFailed && !resultsLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadResults(),
                        'data-attr': 'transactional-email-results-retry',
                    }}
                >
                    These results couldn't load. Try again, or pick a shorter window.
                </LemonBanner>
            ) : !resultsLoading && results?.recipients === 0 ? (
                <p className="text-secondary text-sm m-0">
                    Nobody was sent this email in this period, or the sends named no distinct ID.
                </p>
            ) : (
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
                            results
                                ? `${percentage(results.converted / results.recipients, 1, true)} of them`
                                : undefined
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
            )}
        </div>
    )
}
