import { useActions, useValues } from 'kea'

import { LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from './DropRuleFilterEditor'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const ACTION_OPTIONS: { value: RuleTypeEnumApi; label: string }[] = [
    { value: RuleTypeEnumApi.PathDrop, label: 'Drop' },
    { value: RuleTypeEnumApi.RateLimit, label: 'Rate limit' },
]

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors, serviceTraffic, serviceTrafficLoading } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit

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

            <SceneSection
                title="Match"
                titleSize="sm"
                description="Drop logs matching these filters. Dropped lines are not stored — they will not appear in the UI, exports, or alerts. Already-dropped data cannot be recovered."
            >
                {isRateLimit ? (
                    <p className="text-sm text-secondary m-0">
                        Rate limit applies to every log line from the selected service — no per-line matcher.
                    </p>
                ) : (
                    <DropRuleFilterEditor
                        filterGroup={samplingForm.filter_group}
                        onChange={(group) => setSamplingFormValue('filter_group', group)}
                    />
                )}
            </SceneSection>

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
                        label="Sustained limit (logs per second)"
                        help="Whole number from 1 to 1,000,000. Burst capacity is set automatically (10× sustained)."
                        error={samplingFormErrors.rate_limit_logs_per_second}
                    >
                        <LemonInput
                            value={samplingForm.rate_limit_logs_per_second}
                            onChange={(v) => setSamplingFormValue('rate_limit_logs_per_second', v)}
                            placeholder="e.g. 5000"
                            className="max-w-xs"
                        />
                    </LemonField.Pure>
                )}
            </SceneSection>

            <SceneSection
                title="Scope"
                titleSize="sm"
                description="Limit this rule to one service, or apply it across the whole project."
            >
                <LemonField.Pure
                    label={isRateLimit ? 'Service (required)' : 'Service (optional)'}
                    error={samplingFormErrors.scope_service}
                    help={isRateLimit ? 'Pick a service from the last 24h.' : 'Leave empty to apply to every service.'}
                >
                    <div className="flex flex-col gap-2">
                        <ServiceFilter
                            selectionMode="single"
                            emptyButtonLabel={isRateLimit ? 'Pick from last 24h…' : 'All services'}
                            value={samplingForm.scope_service ? [samplingForm.scope_service] : []}
                            onChange={(names) => setSamplingFormValue('scope_service', names[0] ?? '')}
                            dateRange={{ date_from: '-24h', date_to: null }}
                        />
                        {isRateLimit &&
                            (serviceTrafficLoading ? (
                                <span className="text-muted text-sm">Loading recent volume…</span>
                            ) : serviceTraffic && samplingForm.scope_service.trim() ? (
                                <span className="text-muted text-sm">
                                    ~{serviceTraffic.avg_logs_per_sec.toFixed(2)} logs/sec average over the last 24h (
                                    {serviceTraffic.log_count.toLocaleString()} lines).
                                </span>
                            ) : null)}
                    </div>
                </LemonField.Pure>
            </SceneSection>
        </div>
    )
}
