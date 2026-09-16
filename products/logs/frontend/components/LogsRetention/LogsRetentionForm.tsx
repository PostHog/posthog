import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { LogsFilterVolumeSparkline } from 'products/logs/frontend/components/LogsFilterPreview/LogsFilterVolumeSparkline'
import { DropRuleFilterEditor } from 'products/logs/frontend/components/LogsSampling/DropRuleFilterEditor'
import { LogsFeatureFlagKeys } from 'products/logs/frontend/logsFeatureFlagKeys'

import { logsRetentionFormLogic } from './logsRetentionFormLogic'
import { LogsRetentionPeriodPicker } from './LogsRetentionPeriodPicker'
import { buildRetentionProjection, retentionProjectionText } from './retentionStorageProjection'

export function LogsRetentionForm(): JSX.Element {
    const { retentionForm, retentionFormErrors, suggestedName, suggestedNameLoading } =
        useValues(logsRetentionFormLogic)
    const { setRetentionFormValue, applySuggestedName } = useActions(logsRetentionFormLogic)
    const allowCustomRetention = useFeatureFlag(LogsFeatureFlagKeys.customRetention)

    const hasFilters = retentionForm.filter_group.values.length > 0
    // Hide the hint once it matches what's in the field — the link would be a no-op.
    const showSuggestion = !!suggestedName?.name && suggestedName.name !== retentionForm.name.trim()

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <div className="flex flex-col gap-3">
                <LemonField.Pure
                    label="Name"
                    error={retentionFormErrors.name}
                    help={
                        suggestedNameLoading ? (
                            <span>Suggesting a name…</span>
                        ) : showSuggestion ? (
                            <span className="flex items-center gap-1 flex-wrap">
                                <span>
                                    Suggested: <span className="font-medium">{suggestedName.name}</span>
                                </span>
                                <Link onClick={applySuggestedName}>Use suggested name</Link>
                            </span>
                        ) : undefined
                    }
                >
                    <LemonInput
                        value={retentionForm.name}
                        onChange={(v) => setRetentionFormValue('name', v)}
                        placeholder="e.g. Keep payment logs for 30 days"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Enabled">
                    <LemonSwitch
                        checked={retentionForm.enabled}
                        onChange={(v) => setRetentionFormValue('enabled', v)}
                    />
                </LemonField.Pure>
            </div>

            <SceneSection title="Retention" titleSize="sm">
                <LemonField.Pure label="Keep matching logs for">
                    <LogsRetentionPeriodPicker
                        value={retentionForm.retention_days}
                        onChange={(days) => setRetentionFormValue('retention_days', days)}
                        allowCustom={allowCustomRetention}
                        size="small"
                        dataAttrPrefix="logs-retention-rule"
                    />
                </LemonField.Pure>
            </SceneSection>

            <SceneSection
                title="Match"
                titleSize="sm"
                description="Logs matching these filters use the retention above instead of the environment default. The first matching rule wins."
            >
                <DropRuleFilterEditor
                    filterGroup={retentionForm.filter_group}
                    onChange={(group) => setRetentionFormValue('filter_group', group)}
                />
                {!hasFilters && <p className="text-danger text-xs mt-1 mb-0">Add at least one filter to match logs.</p>}
                <LogsFilterVolumeSparkline
                    filterGroup={retentionForm.filter_group}
                    metric="bytes"
                    renderCaption={({ points }) => {
                        const projection = buildRetentionProjection(points, retentionForm.retention_days)
                        if (!projection) {
                            return null
                        }
                        return (
                            <div className="flex items-center gap-1 text-xs text-muted">
                                <span>{retentionProjectionText(projection, retentionForm.retention_days)}</span>
                                <Tooltip title="Estimated from uncompressed ingested bytes over the last 24 hours — the same measure logs usage is billed on. Batch-level byte counts are spread evenly across records, so this is an approximation.">
                                    <IconInfo className="shrink-0" />
                                </Tooltip>
                            </div>
                        )
                    }}
                />
            </SceneSection>
        </div>
    )
}
