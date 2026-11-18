import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type {
    ExperimentSetupOutcomeApi,
    ExperimentSetupPreviousExperimentApi,
    ExperimentSetupPreviousExperimentsSectionApi,
    PreviousExperimentStateEnumApi,
} from 'products/experiments/frontend/generated/api.schemas'

import { SetupContextSection } from '../SetupContextSection'
import { SetupFactsTable } from '../SetupFactsTable'
import { formatCount, formatTimestamp } from '../setupInspectorUtils'
import { SetupStackedCell } from '../SetupStackedCell'

const STATE_LABELS: Record<PreviousExperimentStateEnumApi, string> = {
    draft: 'Draft',
    running: 'Running',
    paused: 'Paused',
    exposure_frozen: 'Exposure frozen',
    stopped: 'Stopped',
}

function splitLines(experiment: ExperimentSetupPreviousExperimentApi): (string | null)[] {
    const split = experiment.serving_single_variant
        ? `Serves ${experiment.serving_single_variant} only`
        : experiment.split_even === null
          ? 'Boolean flag'
          : experiment.split_even
            ? 'Even split'
            : 'Uneven split'
    return [
        split,
        `${experiment.variant_count} variants`,
        experiment.rollout_percentage === null ? null : `${experiment.rollout_percentage}% rollout`,
    ]
}

function bucketingLines(experiment: ExperimentSetupPreviousExperimentApi): (string | false)[] {
    return [
        experiment.bucketing_identifier === 'device_id' ? 'Device ID' : 'Distinct ID',
        experiment.ensure_experience_continuity && 'Persists across authentication',
        `Evaluated on ${experiment.evaluation_runtime}`,
        experiment.group_aggregation && 'Groups, not persons',
    ]
}

function exposureLines(experiment: ExperimentSetupPreviousExperimentApi): (string | false)[] {
    const event = experiment.custom_exposure_event
        ? `Custom: ${experiment.custom_exposure_event}`
        : experiment.custom_exposure_action_id !== null
          ? `Custom: action ${experiment.custom_exposure_action_id}`
          : 'Default event'
    const filterCount = experiment.exposure_property_filters.length
    return [
        event,
        filterCount > 0 && `${filterCount} property ${filterCount === 1 ? 'filter' : 'filters'}`,
        experiment.activation_event !== null && `Activation: ${experiment.activation_event}`,
        experiment.activation_action_id !== null && `Activation: action ${experiment.activation_action_id}`,
        `Multiple variants: ${experiment.multiple_variant_handling}${experiment.multiple_variant_handling_set ? '' : ' (default)'}`,
        !experiment.filter_test_accounts && 'Test accounts included',
    ]
}

function controlBaseline(outcome: ExperimentSetupOutcomeApi): string | null {
    if (outcome.control_baseline_value === null) {
        return null
    }
    return outcome.metric_type === 'funnel'
        ? `Control ${percentage(outcome.control_baseline_value, 2)}`
        : `Control ${humanFriendlyNumber(outcome.control_baseline_value, 3)} per unit`
}

function outcomeLines(outcome: ExperimentSetupOutcomeApi | null): (string | null)[] {
    if (!outcome) {
        return ['No result']
    }
    return [
        outcome.analyzed_exposures === null
            ? `${formatCount(outcome.metric_samples)} ${outcome.metric_type} samples`
            : `${formatCount(outcome.analyzed_exposures)} analyzed exposures`,
        controlBaseline(outcome),
        outcome.any_variant_significant ? 'A variant is significant' : 'No significant variant',
        `Data through ${formatTimestamp(outcome.result_data_through)}`,
        `Computed ${formatTimestamp(outcome.result_completed_at)}`,
    ]
}

const COLUMNS: LemonTableColumns<ExperimentSetupPreviousExperimentApi> = [
    {
        title: 'Experiment',
        render: (_, experiment) => (
            <LemonTableLink
                to={urls.experiment(experiment.id)}
                target="_blank"
                title={experiment.name}
                description={experiment.feature_flag_key}
            />
        ),
    },
    {
        title: 'State',
        render: (_, experiment) => (
            <SetupStackedCell
                lines={[
                    STATE_LABELS[experiment.state],
                    experiment.start_date ? `Launched ${formatTimestamp(experiment.start_date)}` : null,
                    experiment.end_date ? `Ended ${formatTimestamp(experiment.end_date)}` : null,
                    experiment.conclusion,
                ]}
            />
        ),
    },
    { title: 'Flag', render: (_, experiment) => <SetupStackedCell lines={splitLines(experiment)} /> },
    { title: 'Bucketing', render: (_, experiment) => <SetupStackedCell lines={bucketingLines(experiment)} /> },
    { title: 'Exposure', render: (_, experiment) => <SetupStackedCell lines={exposureLines(experiment)} /> },
    {
        title: 'Metrics',
        render: (_, experiment) => (
            <SetupStackedCell
                lines={[
                    `${experiment.primary_metric_count} primary, ${experiment.secondary_metric_count} secondary, ${experiment.shared_metric_count} shared`,
                    experiment.primary_metric_types.join(', '),
                    [
                        ...experiment.primary_metric_events,
                        ...experiment.primary_metric_action_ids.map((id) => `action ${id}`),
                    ].join(', '),
                    `${experiment.stats_method}${experiment.minimum_detectable_effect === null ? '' : `, MDE ${experiment.minimum_detectable_effect}%`}`,
                    experiment.has_holdout ? 'Holdout' : null,
                ]}
            />
        ),
    },
    { title: 'Outcome', render: (_, experiment) => <SetupStackedCell lines={outcomeLines(experiment.outcome)} /> },
]

export function PreviousExperimentsSection({
    section,
}: {
    section: ExperimentSetupPreviousExperimentsSectionApi
}): JSX.Element {
    const data = section.data
    const summary = data?.summary
    return (
        <SetupContextSection
            title="Previous experiments"
            description="How the project's recent experiments were set up and how they went. Most recently launched first, then drafts. Flag settings are read from each flag as it stands now."
            status={section.status}
        >
            {data && summary && (
                <>
                    <SetupFactsTable
                        facts={[
                            { label: 'Listed', value: String(summary.total) },
                            { label: 'Launched', value: String(summary.launched) },
                            { label: 'Launched without results', value: String(summary.launched_without_results) },
                            {
                                label: 'Launched with 0 analyzed exposures',
                                value: String(summary.launched_with_zero_analyzed_exposures),
                            },
                            {
                                label: 'Launched with under 100 analyzed exposures',
                                value: String(summary.launched_with_under_100_analyzed_exposures),
                            },
                            {
                                label: 'Launched with unknown exposures',
                                value: String(summary.launched_with_unknown_analyzed_exposures),
                                help: 'The result stores no sample counts, or its metric is a retention or a ratio metric, whose samples are not exposures.',
                            },
                            { label: 'Device ID bucketing', value: String(summary.using_device_id_bucketing) },
                            {
                                label: 'Persist flags across authentication',
                                value: String(summary.using_persistence),
                            },
                            { label: 'Custom exposure', value: String(summary.using_custom_exposure) },
                            {
                                label: 'Exposure property filters',
                                value: String(summary.using_exposure_property_filters),
                            },
                            { label: 'Activation', value: String(summary.using_activation) },
                            { label: 'Uneven split', value: String(summary.using_uneven_split) },
                            { label: 'Serving a single variant', value: String(summary.serving_single_variant) },
                        ]}
                    />
                    <LemonTable
                        size="small"
                        rowKey="id"
                        dataSource={data.experiments}
                        columns={COLUMNS}
                        emptyState="This project has no experiments you can see."
                    />
                </>
            )}
        </SetupContextSection>
    )
}
