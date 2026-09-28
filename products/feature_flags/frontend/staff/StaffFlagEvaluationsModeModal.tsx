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
    0: 'The Usage tab reads $feature_flag_called events from the events table.',
    1: 'The Usage tab reads the flag_evaluations table, and the table is available in SQL. While the FLAG_EVALUATIONS_USAGE_TAB_FORCE_EVENTS instance setting is on, the Usage tab reads the events table instead.',
    2: 'The Usage tab reads the flag_evaluations table, and the table is available in SQL. Ingestion also stops writing $feature_flag_called to the events table.',
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
            description="Choose which table the flag Usage tab reads $feature_flag_called data from. The mode applies to the whole organization of each selected team."
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
                        Ingestion doesn't act on this mode yet, so it still writes $feature_flag_called to the events
                        table for organizations on it. Once ingestion supports this mode, it stops those writes.
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
