import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { UniversalFiltersGroup } from '~/types'

import { DropRuleFilterEditor } from 'products/logs/frontend/components/LogsSampling/DropRuleFilterEditor'
import { DropRuleSparklinePreview } from 'products/logs/frontend/components/LogsSampling/DropRuleSparklinePreview'
import { ServiceFilter } from 'products/logs/frontend/components/LogsViewer/Filters/ServiceFilter'
import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { logsSamplingFormLogic } from './logsSamplingFormLogic'
import { ruleTypeLabel } from './ruleTypeLabel'

const RULE_TYPE_OPTIONS_CREATE: { value: RuleTypeEnumApi; label: string }[] = [
    {
        value: RuleTypeEnumApi.PathDrop,
        label: 'Drop',
    },
    {
        value: RuleTypeEnumApi.RateLimit,
        label: 'Rate limit by service (logs/sec)',
    },
]

export function LogsSamplingForm(): JSX.Element {
    const {
        samplingForm,
        samplingFormErrors,
        simulation,
        simulationLoading,
        canSimulate,
        isNewRule,
        serviceTraffic,
        serviceTrafficLoading,
    } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isPathDrop = samplingForm.rule_type === RuleTypeEnumApi.PathDrop
    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <LemonBanner type="warning">
                When this rule is <strong>enabled</strong> and matches a log line, that line is{' '}
                <strong>not stored</strong>. Dropped logs do not appear in the UI, exports, or alerts. Disabling the
                rule or editing patterns only affects <em>new</em> ingestion—already dropped data cannot be recovered.
            </LemonBanner>
            {canSimulate && (
                <LemonBanner type="info">
                    {simulationLoading
                        ? 'Estimating impact…'
                        : simulation
                          ? `Rough drop estimate: ~${simulation.estimated_reduction_pct.toFixed(1)}%. ${simulation.notes}`
                          : 'Impact estimate will appear after you save or change the rule.'}
                </LemonBanner>
            )}
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
            {isNewRule ? (
                <LemonField.Pure
                    label="Action"
                    info="You can create multiple rules; lower priority number runs first. The first rule that matches wins for each log line."
                >
                    <LemonSelect
                        options={RULE_TYPE_OPTIONS_CREATE}
                        value={samplingForm.rule_type}
                        onChange={(v) => v && setSamplingFormValue('rule_type', v)}
                    />
                </LemonField.Pure>
            ) : (
                <LemonField.Pure label="Rule type">
                    <LemonTag>{ruleTypeLabel(samplingForm.rule_type)}</LemonTag>
                </LemonField.Pure>
            )}
            {isRateLimit ? (
                <>
                    <LemonBanner type="info">
                        <div className="text-sm">
                            <strong>Which service?</strong> This must match the log&apos;s OpenTelemetry{' '}
                            <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">service.name</code>{' '}
                            exactly (same string as the Service column or log details—no wildcards, case-sensitive).
                            Example:{' '}
                            <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">payment-api</code>.
                        </div>
                    </LemonBanner>
                    <LemonField.Pure
                        label="Service"
                        help="Pick from names seen in the last 24h, or type the full name in the field below if it does not appear in the list."
                        error={samplingFormErrors.scope_service}
                    >
                        <div className="flex flex-col gap-2">
                            <ServiceFilter
                                selectionMode="single"
                                emptyButtonLabel="Pick from last 24h…"
                                value={samplingForm.scope_service ? [samplingForm.scope_service] : []}
                                onChange={(names) => setSamplingFormValue('scope_service', names[0] ?? '')}
                                dateRange={{ date_from: '-24h', date_to: null }}
                            />
                            <LemonInput
                                value={samplingForm.scope_service}
                                onChange={(v) => setSamplingFormValue('scope_service', v)}
                                placeholder="Type exact service.name (required)"
                            />
                            {serviceTrafficLoading ? (
                                <span className="text-muted text-sm">Loading recent volume…</span>
                            ) : serviceTraffic && samplingForm.scope_service.trim() ? (
                                <span className="text-muted text-sm">
                                    ~{serviceTraffic.avg_logs_per_sec.toFixed(2)} logs/sec average over the last 24h (
                                    {serviceTraffic.log_count.toLocaleString()} lines).
                                </span>
                            ) : null}
                        </div>
                    </LemonField.Pure>
                </>
            ) : null}
            {isPathDrop ? <PathDropFilterSection /> : null}
            {isRateLimit ? (
                <>
                    <LemonBanner type="info">
                        <div className="text-sm">
                            <strong>How limits work:</strong> lines above your sustained cap are dropped at ingestion.
                            Optional <strong>burst</strong> is how many lines can be stored in a short spike before the
                            limiter pulls you back toward the sustained rate. Example: sustained{' '}
                            <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">100</code>, burst{' '}
                            <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">300</code> — you can admit
                            up to 300 lines quickly, then stored volume trends toward ~100/sec for this service.
                        </div>
                    </LemonBanner>
                    <LemonField.Pure
                        label="Sustained limit (lines per second)"
                        help="Whole number from 1 to 1,000,000. Average stored lines/sec for this service while this rule is the first match."
                        error={samplingFormErrors.rate_limit_logs_per_second}
                    >
                        <LemonInput
                            value={samplingForm.rate_limit_logs_per_second}
                            onChange={(v) => setSamplingFormValue('rate_limit_logs_per_second', v)}
                            placeholder="e.g. 5000"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Burst capacity (optional)"
                        help="Whole number at least equal to sustained, up to 60,000,000, or leave empty for 3× sustained. Larger burst allows a bigger one-off spike before extra lines drop."
                        error={samplingFormErrors.rate_limit_burst_logs}
                    >
                        <LemonInput
                            value={samplingForm.rate_limit_burst_logs}
                            onChange={(v) => setSamplingFormValue('rate_limit_burst_logs', v)}
                            placeholder="Empty = 3× sustained"
                        />
                    </LemonField.Pure>
                </>
            ) : null}
        </div>
    )
}

function PathDropFilterSection(): JSX.Element {
    const { samplingForm, samplingFormErrors } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const onFilterGroupChange = useCallback(
        (group: UniversalFiltersGroup) => setSamplingFormValue('path_drop_filter_group', group),
        [setSamplingFormValue]
    )

    return (
        <>
            <LemonField.Pure label="Drop logs matching" error={samplingFormErrors.path_drop_filter_group}>
                <DropRuleFilterEditor
                    filterGroup={samplingForm.path_drop_filter_group}
                    onChange={onFilterGroupChange}
                />
            </LemonField.Pure>
            <DropRuleSparklinePreview />
        </>
    )
}
