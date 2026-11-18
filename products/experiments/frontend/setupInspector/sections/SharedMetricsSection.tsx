import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import type {
    ExperimentSetupSharedMetricApi,
    ExperimentSetupSharedMetricsSectionApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { formatTimestamp, formatYesNo } from '../setupInspectorUtils'
import { SetupStackedCell } from '../SetupStackedCell'

export function SharedMetricsSection({ section }: { section: ExperimentSetupSharedMetricsSectionApi }): JSX.Element {
    const data = section.data
    return (
        <SetupContextSection
            title="Shared metrics"
            description="The shared metrics the project reuses most. With a metric event, the ones that count it come first."
            status={section.status}
        >
            {data && (
                <>
                    {data.metric_event_match_truncated && (
                        <p className="text-sm mb-0">
                            The project has more shared metrics than the match could read, so a match further down may
                            be missing.
                        </p>
                    )}
                    <LemonTable<ExperimentSetupSharedMetricApi>
                        size="small"
                        rowKey="id"
                        dataSource={data.metrics}
                        emptyState="This project has no shared metrics you can see."
                        columns={[
                            {
                                title: 'Shared metric',
                                render: (_, metric) => (
                                    <LemonTableLink
                                        to={urls.experimentsSharedMetric(metric.id)}
                                        target="_blank"
                                        title={metric.name}
                                        description={metric.metric_type ?? 'Legacy metric'}
                                    />
                                ),
                            },
                            {
                                title: 'Events and actions',
                                render: (_, metric) => (
                                    <SetupStackedCell
                                        lines={[
                                            metric.events.join(', '),
                                            ...metric.action_ids.map((id) => `action ${id}`),
                                        ]}
                                    />
                                ),
                            },
                            {
                                title: 'Used',
                                render: (_, metric) => (
                                    <SetupStackedCell
                                        lines={[
                                            `${metric.used_as_primary} primary, ${metric.used_as_secondary} secondary`,
                                            metric.last_used_at
                                                ? `Last used ${formatTimestamp(metric.last_used_at)}`
                                                : 'Never used',
                                        ]}
                                    />
                                ),
                            },
                            {
                                title: `Counts ${data.metric_event ?? 'the metric event'}`,
                                render: (_, metric) =>
                                    metric.matches_metric_event === null ? (
                                        <span className="text-secondary text-xs">No metric event passed</span>
                                    ) : (
                                        <SetupStackedCell
                                            lines={[
                                                formatYesNo(metric.matches_metric_event),
                                                (metric.metric_event_roles ?? []).join(', '),
                                            ]}
                                        />
                                    ),
                            },
                        ]}
                    />
                </>
            )}
        </SetupContextSection>
    )
}
