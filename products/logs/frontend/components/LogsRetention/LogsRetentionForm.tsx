import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { DropRuleFilterEditor } from 'products/logs/frontend/components/LogsSampling/DropRuleFilterEditor'

import { RETENTION_DAYS_OPTIONS, logsRetentionFormLogic } from './logsRetentionFormLogic'

const RETENTION_OPTIONS = RETENTION_DAYS_OPTIONS.map((days) => ({ value: days, label: `${days} days` }))

export function LogsRetentionForm(): JSX.Element {
    const { retentionForm, retentionFormErrors } = useValues(logsRetentionFormLogic)
    const { setRetentionFormValue } = useActions(logsRetentionFormLogic)

    const hasFilters = retentionForm.filter_group.values.length > 0

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="Name" error={retentionFormErrors.name}>
                    <LemonInput
                        value={retentionForm.name}
                        onChange={(v) => setRetentionFormValue('name', v)}
                        placeholder="e.g. Keep payment logs for 90 days"
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
                    <LemonSegmentedButton
                        value={retentionForm.retention_days}
                        onChange={(v) => v && setRetentionFormValue('retention_days', v)}
                        options={RETENTION_OPTIONS}
                        size="small"
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
            </SceneSection>
        </div>
    )
}
