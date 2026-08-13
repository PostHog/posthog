import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { LogsFilterVolumeSparkline } from 'products/logs/frontend/components/LogsFilterPreview/LogsFilterVolumeSparkline'
import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from './DropRuleFilterEditor'
import { RateLimitUnit, logsSamplingFormLogic, rateLimitAmountToKbPerSecond } from './logsSamplingFormLogic'

const RATE_LIMIT_UNIT_OPTIONS: { value: RateLimitUnit; label: string }[] = [
    { value: 'KB/s', label: 'KB/s' },
    { value: 'MB/s', label: 'MB/s' },
    { value: 'GB/s', label: 'GB/s' },
]

const ACTION_OPTIONS: { value: RuleTypeEnumApi; label: string }[] = [
    { value: RuleTypeEnumApi.PathDrop, label: 'Drop' },
    { value: RuleTypeEnumApi.RateLimit, label: 'Rate limit' },
]

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit
    const hasFilters = samplingForm.filter_group.values.length > 0

    const matchDescription = isRateLimit
        ? `Drop logs matching these filters above ${
              samplingForm.rate_limit_amount.trim()
                  ? `${samplingForm.rate_limit_amount.trim()} ${samplingForm.rate_limit_unit}`
                  : 'the configured rate limit'
          }.`
        : 'Drop logs matching these filters. Dropped lines are not stored — they will not appear in the UI, exports, or alerts. Already-dropped data cannot be recovered.'

    /** Rate limit projected onto the same y-axis units the chart uses (bytes/bucket). */
    const rateLimitThresholdPerBucket = (bucketSeconds: number): number | null => {
        if (!isRateLimit || bucketSeconds <= 0) {
            return null
        }
        const kbPerSecond = rateLimitAmountToKbPerSecond(samplingForm.rate_limit_amount, samplingForm.rate_limit_unit)
        if (!Number.isFinite(kbPerSecond) || kbPerSecond <= 0) {
            return null
        }
        // KB/s × 1000 = bytes/s, × bucket width in seconds = bytes/bucket.
        return kbPerSecond * 1000 * bucketSeconds
    }

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="Name" error={samplingFormErrors.name}>
                    <LemonInput
                        value={samplingForm.name}
                        onChange={(v) => setSamplingFormValue('name', v)}
                        placeholder="e.g. Drop noisy health checks"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Enabled">
                    <LemonSwitch checked={samplingForm.enabled} onChange={(v) => setSamplingFormValue('enabled', v)} />
                </LemonField.Pure>
            </div>

            <SceneSection title="Action" titleSize="sm">
                <LemonField.Pure label="What to do when a log matches">
                    <LemonSegmentedButton
                        value={samplingForm.rule_type}
                        onChange={(v) => v && setSamplingFormValue('rule_type', v)}
                        options={ACTION_OPTIONS}
                        size="small"
                    />
                </LemonField.Pure>
                {isRateLimit && (
                    <LemonField.Pure
                        label="Rate limit"
                        help="Minimum 1 KB/s, maximum 1 GB/s. Fractional values allowed (e.g. 1.5 MB/s)."
                        error={samplingFormErrors.rate_limit_amount}
                    >
                        <div className="flex gap-2 items-center max-w-sm">
                            <LemonInput
                                value={samplingForm.rate_limit_amount}
                                onChange={(v) => setSamplingFormValue('rate_limit_amount', v)}
                                placeholder="e.g. 5"
                                inputMode="decimal"
                            />
                            <LemonSelect<RateLimitUnit>
                                value={samplingForm.rate_limit_unit}
                                onChange={(v) => v && setSamplingFormValue('rate_limit_unit', v)}
                                options={RATE_LIMIT_UNIT_OPTIONS}
                            />
                        </div>
                    </LemonField.Pure>
                )}
            </SceneSection>

            <SceneSection title="Match" titleSize="sm" description={matchDescription}>
                <DropRuleFilterEditor
                    filterGroup={samplingForm.filter_group}
                    onChange={(group) => setSamplingFormValue('filter_group', group)}
                />
                {/* filter_group is an object — kea-forms types only allow scalar field errors,
                    so this inline message mirrors what samplingFormSaveDisabledReason returns. */}
                {!hasFilters && <p className="text-danger text-xs mt-1 mb-0">Add at least one filter to match logs.</p>}
                <LogsFilterVolumeSparkline
                    filterGroup={samplingForm.filter_group}
                    metric={isRateLimit ? 'bytes' : 'count'}
                    buildGoalLines={({ bucketSeconds }) => {
                        const threshold = rateLimitThresholdPerBucket(bucketSeconds)
                        if (threshold == null) {
                            return undefined
                        }
                        return [
                            {
                                value: threshold,
                                color: 'var(--danger)',
                                label: `Rate limit (${samplingForm.rate_limit_amount.trim()} ${
                                    samplingForm.rate_limit_unit
                                })`,
                                displayLabel: true,
                            },
                        ]
                    }}
                    renderCaption={({ bucketSeconds, chartMax }) => {
                        const threshold = rateLimitThresholdPerBucket(bucketSeconds)
                        if (threshold == null || chartMax <= 0 || threshold <= chartMax) {
                            return null
                        }
                        return (
                            <div className="text-xs text-muted">
                                Rate limit is above the current peak — no logs would be dropped in the previewed window.
                            </div>
                        )
                    }}
                />
            </SceneSection>
        </div>
    )
}
