import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTableColumns,
    Spinner,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils/strings'

import { FlagEvaluationsModeEnumApi, StaffOrganizationModeChangeApi } from '../generated/api.schemas'
import { FLAG_EVALUATIONS_MODE_LABELS, featureFlagsStaffToolsLogic } from './featureFlagsStaffToolsLogic'

const MODE_DESCRIPTIONS: Record<FlagEvaluationsModeEnumApi, string> = {
    0: 'Every reader of $feature_flag_called reads the events table.',
    1: "The Usage tab, the per-project counts on a flag's Projects tab, events lists filtered to $feature_flag_called, and the home page flag call and enrollment counts read the flag_evaluations table. So does a HogQL query that pins $feature_flag_called to flag keys within the table's coverage. Other queries, including default experiment exposures, read the events table. Event pickers hide $feature_flag_called. New action steps on it are refused, and so are new cohort criteria on it that the cohort calculation would read from the events table. While the FLAG_EVALUATIONS_READS_FORCE_EVENTS instance setting is on, all of this uses the events table instead.",
    2: "Reads as mode 1. Ingestion also stops writing $feature_flag_called to the events table for the teams it copies to flag_evaluations. HogQL queries read flag_evaluations for any date range and fail when they can't, realtime cohorts refuse new $feature_flag_called criteria, and flags keep no last called time unless it syncs from flag_evaluations.",
}

export function StaffFlagEvaluationsModeModal(): JSX.Element {
    const {
        isFlagEvaluationsModeModalOpen,
        flagEvaluationsModeRequest,
        flagEvaluationsModePreviewLoading,
        flagEvaluationsModePreviewSummary,
        flagEvaluationsModeResultLoading,
    } = useValues(featureFlagsStaffToolsLogic)
    const {
        closeFlagEvaluationsModeModal,
        setFlagEvaluationsModeRequest,
        loadFlagEvaluationsModePreview,
        applyFlagEvaluationsMode,
    } = useActions(featureFlagsStaffToolsLogic)

    const { mode, allowDowngrade } = flagEvaluationsModeRequest

    const columns: LemonTableColumns<StaffOrganizationModeChangeApi> = [
        { title: 'Organization', dataIndex: 'organization_name' },
        { title: 'Teams', dataIndex: 'team_count' },
        {
            title: 'Experiments needing $feature_flag_called in events',
            dataIndex: 'running_experiments_needing_flag_calls_in_events',
        },
        {
            title: 'Current mode',
            key: 'current_mode',
            render: (_, organization) => FLAG_EVALUATIONS_MODE_LABELS[organization.current_mode],
        },
        {
            title: 'New mode',
            key: 'new_mode',
            render: (_, organization) =>
                organization.changed ? (
                    FLAG_EVALUATIONS_MODE_LABELS[organization.target_mode]
                ) : (
                    <span className="text-secondary">Unchanged</span>
                ),
        },
    ]

    const summary = flagEvaluationsModePreviewSummary
    const applyDisabledReason = !summary
        ? flagEvaluationsModePreviewLoading
            ? 'Wait for the preview to load'
            : 'Retry the preview first'
        : summary.organizationsChanged === 0
          ? 'No organization would change'
          : undefined
    const applyingReason = flagEvaluationsModeResultLoading ? 'Wait for the move to finish' : undefined

    return (
        <LemonModal
            title="Set flag evaluations mode"
            description="Choose which table $feature_flag_called data is read from. The mode applies to the whole organization of each selected team."
            isOpen={isFlagEvaluationsModeModalOpen}
            onClose={closeFlagEvaluationsModeModal}
            closable={!flagEvaluationsModeResultLoading}
            width={640}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeFlagEvaluationsModeModal}
                        disabledReason={applyingReason}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => applyFlagEvaluationsMode()}
                        loading={flagEvaluationsModeResultLoading}
                        disabledReason={applyDisabledReason}
                        data-attr="ff-staff-flag-evaluations-mode-apply"
                    >
                        {summary?.organizationsChanged
                            ? `Move ${pluralize(summary.organizationsChanged, 'organization')}`
                            : 'Move organizations'}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <LemonField.Pure label="Mode" help={MODE_DESCRIPTIONS[mode]}>
                    <LemonSelect
                        value={mode}
                        onChange={(newMode) => setFlagEvaluationsModeRequest({ mode: newMode })}
                        disabledReason={applyingReason}
                        options={Object.values(FlagEvaluationsModeEnumApi).map((value) => ({
                            value,
                            label: FLAG_EVALUATIONS_MODE_LABELS[value],
                        }))}
                    />
                </LemonField.Pure>

                {mode === FlagEvaluationsModeEnumApi.Number2 && (
                    <LemonBanner type="warning">
                        For the teams ingestion copies to flag_evaluations, it writes $feature_flag_called only there,
                        so a failed write loses the event. Teams in INGESTION_FLAG_EVALUATIONS_EXCLUDED_TEAMS still
                        write to the events table, and so does every team while INGESTION_FLAG_EVALUATIONS_ONLY_DISABLED
                        is on.
                    </LemonBanner>
                )}

                <LemonCheckbox
                    checked={allowDowngrade}
                    onChange={(checked) => setFlagEvaluationsModeRequest({ allowDowngrade: checked })}
                    disabledReason={applyingReason}
                    label="Also lower organizations that are above this mode"
                />

                {flagEvaluationsModePreviewLoading ? (
                    <div className="flex justify-center p-4">
                        <Spinner className="text-2xl" />
                    </div>
                ) : !summary ? (
                    <div className="flex items-center justify-center gap-2 p-4">
                        <span className="text-secondary">Couldn't load the preview.</span>
                        <LemonButton type="secondary" size="small" onClick={() => loadFlagEvaluationsModePreview()}>
                            Retry
                        </LemonButton>
                    </div>
                ) : (
                    <div className="space-y-2">
                        <LemonTable
                            size="small"
                            dataSource={summary.organizations}
                            columns={columns}
                            rowKey="organization_id"
                        />
                        {summary.experimentsNeedingFlagCallsInEvents > 0 && (
                            <LemonBanner type="warning">
                                These organizations run{' '}
                                {pluralize(summary.experimentsNeedingFlagCallsInEvents, 'experiment')} that read
                                $feature_flag_called from the events table through an exposure action, an activation
                                event, or a metric. Those reads find no new calls once the organization moves to{' '}
                                {FLAG_EVALUATIONS_MODE_LABELS[FlagEvaluationsModeEnumApi.Number2]}.
                            </LemonBanner>
                        )}
                        {summary.organizationsLoweredFromFlagEvaluationsOnly > 0 && (
                            <LemonBanner type="warning">
                                Lowering{' '}
                                {pluralize(summary.organizationsLoweredFromFlagEvaluationsOnly, 'organization')} from{' '}
                                {FLAG_EVALUATIONS_MODE_LABELS[FlagEvaluationsModeEnumApi.Number2]} restarts any events
                                writes ingestion stopped for them, but the events table keeps a gap for that time.
                            </LemonBanner>
                        )}
                        {summary.organizationsLeftAboveMode > 0 && (
                            <p className="text-secondary mb-0">
                                {pluralize(summary.organizationsLeftAboveMode, 'organization')} above this mode will
                                stay there. Select "Also lower organizations that are above this mode" to move them.
                            </p>
                        )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
