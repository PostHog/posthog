import type { ExperimentSetupCandidateMetricSectionApi } from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatPropertyFilters, formatShare, formatTimestamp, formatYesNo } from '../setupInspectorUtils'

export function CandidateMetricSection({
    section,
}: {
    section: ExperimentSetupCandidateMetricSectionApi
}): JSX.Element {
    const data = section.data
    const funnel = data?.funnel_baseline_stats
    const meanCount = data?.mean_count_baseline_stats
    return (
        <SetupContextSection
            title="Candidate metric"
            description="Traffic and baseline of the candidate primary metric. The baselines are the input the running time calculator takes."
            status={section.status}
            skippedMessage="Pick an event in step 2 above to read this section."
        >
            {data && (
                <SetupFactsTable
                    facts={[
                        { label: 'Metric event', value: data.source_event },
                        { label: 'Property filters', value: formatPropertyFilters(data.metric_properties) },
                        { label: 'Target event', value: data.target_event ?? 'None' },
                        { label: 'Test accounts filtered', value: formatYesNo(data.test_accounts_filtered) },
                        {
                            label: 'Event volume',
                            value: formatCount(data.event_volume),
                            help: 'A volume of 0 means the event did not occur under these filters. Check the event name.',
                        },
                        { label: 'Unique persons', value: formatCount(data.unique_persons) },
                        { label: 'Persons reached', value: formatCount(data.persons_reached) },
                        {
                            label: 'Persons converted',
                            value: formatCount(data.persons_converted),
                            help: 'Persons who sent the metric event at or after their first target event.',
                        },
                        { label: 'Conversion rate', value: formatShare(data.conversion_rate) },
                        {
                            label: 'Funnel baseline',
                            value: funnel
                                ? `${formatCount(funnel.number_of_samples)} samples, step counts ${funnel.step_counts.join(', ')}`
                                : 'None',
                        },
                        {
                            label: 'Mean count baseline',
                            value: meanCount
                                ? `${formatCount(meanCount.number_of_samples)} samples, sum ${formatCount(meanCount.sum)}, sum of squares ${formatCount(meanCount.sum_squares)}`
                                : 'None',
                            help: data.note ?? undefined,
                        },
                        { label: 'Window', value: `Last ${data.window_days} days` },
                        { label: 'Computed at', value: formatTimestamp(data.computed_at) },
                    ]}
                />
            )}
        </SetupContextSection>
    )
}
