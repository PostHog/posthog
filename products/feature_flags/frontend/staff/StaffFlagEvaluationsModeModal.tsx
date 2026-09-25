import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonModal,
    LemonSegmentedButton,
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
    1: 'The Usage tab reads the flag_evaluations table, and the table is available in SQL.',
    2: 'Same as Read flag evaluations, and ingestion stops writing $feature_flag_called to the events table.',
}

export function StaffFlagEvaluationsModeModal(): JSX.Element {
    const {
        isFlagEvaluationsModeModalOpen,
        flagEvaluationsModeRequest,
        flagEvaluationsModePreviewLoading,
        flagEvaluationsModePreviewSummary,
        flagEvaluationsModeResultLoading,
        selectedTeamIds,
        selectedOrganizationIds,
    } = useValues(featureFlagsStaffToolsLogic)
    const {
        closeFlagEvaluationsModeModal,
        setFlagEvaluationsModeRequest,
        loadFlagEvaluationsModePreview,
        applyFlagEvaluationsMode,
    } = useActions(featureFlagsStaffToolsLogic)

    const { scope, mode, allowDowngrade } = flagEvaluationsModeRequest

    const columns: LemonTableColumns<StaffOrganizationModeChangeApi> = [
        { title: 'Organization', dataIndex: 'organization_name' },
        {
            title: 'Teams',
            key: 'teams',
            render: (_, organization) =>
                organization.team_count === organization.organization_team_count
                    ? organization.team_count
                    : `${organization.team_count} of ${organization.organization_team_count}`,
        },
        { title: 'Will change', dataIndex: 'teams_changed' },
        {
            title: 'Unchanged',
            key: 'unchanged',
            render: (_, organization) => organization.team_count - organization.teams_changed,
        },
    ]

    const summary = flagEvaluationsModePreviewSummary
    const applyDisabledReason = !summary
        ? flagEvaluationsModePreviewLoading
            ? 'Wait for the preview to load'
            : 'Retry the preview first'
        : summary.teamsChanged === 0
          ? 'No team would change'
          : undefined
    const applyingReason = flagEvaluationsModeResultLoading ? 'Wait for the move to finish' : undefined

    return (
        <LemonModal
            title="Set flag evaluations mode"
            description="Choose which table the flag Usage tab reads $feature_flag_called data from."
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
                        {summary?.teamsChanged ? `Move ${pluralize(summary.teamsChanged, 'team')}` : 'Move teams'}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <LemonField.Pure label="Apply to">
                    <LemonSegmentedButton
                        value={scope}
                        onChange={(newScope) => setFlagEvaluationsModeRequest({ scope: newScope })}
                        disabledReason={applyingReason}
                        options={[
                            { value: 'teams', label: `Selected teams (${selectedTeamIds.length})` },
                            {
                                value: 'organizations',
                                label: `Their organizations (${selectedOrganizationIds.length})`,
                            },
                        ]}
                    />
                </LemonField.Pure>

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
                        Ingestion doesn't act on this mode yet, so teams on it behave like Read flag evaluations. Once
                        ingestion supports it, they stop writing $feature_flag_called to the events table.
                    </LemonBanner>
                )}

                <LemonCheckbox
                    checked={allowDowngrade}
                    onChange={(checked) => setFlagEvaluationsModeRequest({ allowDowngrade: checked })}
                    disabledReason={applyingReason}
                    label="Also lower teams that are above this mode"
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
                        {summary.teamsLeftAboveMode > 0 && (
                            <p className="text-secondary mb-0">
                                {pluralize(summary.teamsLeftAboveMode, 'team')} above this mode will stay there. Select
                                "Also lower teams that are above this mode" to move them.
                            </p>
                        )}
                        {summary.teamsOutsideRequest > 0 && (
                            <p className="text-secondary mb-0">
                                {pluralize(summary.teamsOutsideRequest, 'other team')} in these organizations will keep
                                their current mode. A new project copies the highest mode in its organization.
                            </p>
                        )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
