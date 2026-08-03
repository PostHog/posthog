import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSegmentedButtonOption, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { AvailableFeature } from '~/types'

import { DropRuleFilterEditor } from 'products/logs/frontend/components/LogsSampling/DropRuleFilterEditor'

import { RETENTION_DAYS_OPTIONS, logsRetentionFormLogic } from './logsRetentionFormLogic'

export function LogsRetentionForm(): JSX.Element {
    const { retentionForm, retentionFormErrors } = useValues(logsRetentionFormLogic)
    const { setRetentionFormValue } = useActions(logsRetentionFormLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const hasFilters = retentionForm.filter_group.values.length > 0

    // Gate paid tiers on the org entitlement, mirroring the team-wide LogsRetentionSettings — the
    // backend rejects an unentitled tier with a 403, so disable it here rather than fail on save.
    const retentionOptions: LemonSegmentedButtonOption<number>[] = RETENTION_DAYS_OPTIONS.map((days) => ({
        value: days,
        label: `${days} days`,
        disabledReason:
            days === 30 && !hasAvailableFeature(AvailableFeature.LOGS_RETENTION_30D)
                ? 'Upgrade to a paid plan to use 30-day retention'
                : undefined,
    }))

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="Name" error={retentionFormErrors.name}>
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
                    <LemonSegmentedButton
                        value={retentionForm.retention_days}
                        onChange={(v) => v && setRetentionFormValue('retention_days', v)}
                        options={retentionOptions}
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
