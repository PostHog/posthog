import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingFormType, SeverityActionChoice } from './logsSamplingFormLogic'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const RULE_TYPE_OPTIONS_CREATE: { value: RuleTypeEnumApi; label: string }[] = [
    {
        value: RuleTypeEnumApi.PathDrop,
        label: 'Drop when matched (regex patterns)',
    },
    {
        value: RuleTypeEnumApi.SeveritySampling,
        label: 'Drop or sample by severity',
    },
]

const ACTION_OPTIONS: { value: SeverityActionChoice; label: string }[] = [
    { value: 'keep', label: 'Keep' },
    { value: 'drop', label: 'Drop' },
    { value: 'sample', label: 'Sample' },
]

function SeverityRow({
    label,
    actionKey,
    rateKey,
}: {
    label: string
    actionKey: keyof LogsSamplingFormType
    rateKey: keyof LogsSamplingFormType
}): JSX.Element {
    const { samplingForm } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)
    const action = samplingForm[actionKey] as SeverityActionChoice
    const rate = samplingForm[rateKey] as number

    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="w-24 text-muted">{label}</span>
            <LemonSelect
                options={ACTION_OPTIONS}
                value={action}
                onChange={(v) => v && setSamplingFormValue(actionKey, v)}
            />
            {action === 'sample' && (
                <LemonField.Pure label="Rate" className="mb-0">
                    <LemonInput
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={rate}
                        onChange={(v) =>
                            setSamplingFormValue(rateKey, typeof v === 'number' ? v : parseFloat(String(v)) || 0)
                        }
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}

function ruleTypeLabel(ruleType: RuleTypeEnumApi): string {
    if (ruleType === RuleTypeEnumApi.PathDrop) {
        return 'Drop when matched'
    }
    if (ruleType === RuleTypeEnumApi.SeveritySampling) {
        return 'Severity-based'
    }
    return ruleType
}

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, simulation, simulationLoading, canSimulate, isNewRule } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isPathDrop = samplingForm.rule_type === RuleTypeEnumApi.PathDrop
    const isSeverity = samplingForm.rule_type === RuleTypeEnumApi.SeveritySampling

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <LemonBanner type="error">
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
            <LemonField.Pure label="Name">
                <LemonInput
                    value={samplingForm.name}
                    onChange={(v) => setSamplingFormValue('name', v)}
                    placeholder="e.g. Drop noisy health checks"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Enabled"
                info="Turn off to stop this rule from running. Other rules and project defaults still apply."
            >
                <LemonSwitch checked={samplingForm.enabled} onChange={(v) => setSamplingFormValue('enabled', v)} />
            </LemonField.Pure>
            {isNewRule ? (
                <LemonField.Pure
                    label="What should this rule do?"
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
            <LemonField.Pure
                label="Scope: service name (optional)"
                info="If set, the rule only runs for logs from this service.name. Leave empty to apply to all services."
            >
                <LemonInput
                    value={samplingForm.scope_service}
                    onChange={(v) => setSamplingFormValue('scope_service', v)}
                    placeholder="Empty = all services"
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Restrict to path (regex, optional)"
                info="If set, the rule only applies when this regex matches the same path-like value ingestion uses (first non-empty among url.path, http.path, http.route, path). This is a scope filter, not the list of strings to drop."
            >
                <LemonInput
                    value={samplingForm.scope_path_pattern}
                    onChange={(v) => setSamplingFormValue('scope_path_pattern', v)}
                    placeholder="e.g. ^/api/internal/"
                />
            </LemonField.Pure>
            {isPathDrop ? (
                <>
                    <LemonField.Pure
                        label="Attribute key (optional)"
                        info="Leave empty to match patterns against the default path-like attributes (same order as scope above). If you set a key, every pattern line is tested only against that one string attribute—useful for non-HTTP dimensions. One key per rule; there is no AND/OR builder across multiple keys yet."
                        help="Patterns are still OR’d: any single matching line drops the log."
                    >
                        <LemonInput
                            value={samplingForm.path_drop_match_attribute_key}
                            onChange={(v) => setSamplingFormValue('path_drop_match_attribute_key', v)}
                            placeholder="http.route"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Patterns to drop (regex, one per line)"
                        info={
                            <>
                                Each non-empty line is its own JavaScript-style regular expression. If{' '}
                                <strong>any</strong> pattern matches the string from the attribute key (or the default
                                path-like value), the log line is dropped. Invalid regex lines are skipped at
                                ingestion—test patterns carefully.
                            </>
                        }
                    >
                        <LemonTextArea
                            value={samplingForm.path_drop_patterns}
                            onChange={(v) => setSamplingFormValue('path_drop_patterns', v)}
                            placeholder={'/healthz\n/metrics'}
                            rows={4}
                        />
                    </LemonField.Pure>
                </>
            ) : null}
            {isSeverity ? (
                <>
                    <LemonBanner type="warning">
                        Severity rules run at ingestion in order with your other rules. <strong>Drop</strong> removes
                        the line. <strong>Sample</strong> keeps a random fraction per trace id (deterministic for the
                        same trace). Use <strong>Keep</strong> to leave that level unchanged by this rule.
                    </LemonBanner>
                    <div className="font-semibold">Per severity level</div>
                    <SeverityRow label="Debug" actionKey="severity_debug" rateKey="severity_debug_rate" />
                    <SeverityRow label="Info" actionKey="severity_info" rateKey="severity_info_rate" />
                    <SeverityRow label="Warn" actionKey="severity_warn" rateKey="severity_warn_rate" />
                    <SeverityRow label="Error" actionKey="severity_error" rateKey="severity_error_rate" />
                    <div className="font-semibold mt-2">Always keep (optional)</div>
                    <LemonField.Pure
                        label="HTTP status >="
                        className="max-w-xs"
                        info="Logs with this HTTP status or higher are never dropped or sampled by this rule, when the status attribute is present."
                    >
                        <LemonInput
                            value={samplingForm.always_keep_status_gte}
                            onChange={(v) => setSamplingFormValue('always_keep_status_gte', v)}
                            placeholder="e.g. 500"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Latency greater than (ms)"
                        className="max-w-xs"
                        info="Logs slower than this threshold are always kept when duration attributes are present."
                    >
                        <LemonInput
                            value={samplingForm.always_keep_latency_ms_gt}
                            onChange={(v) => setSamplingFormValue('always_keep_latency_ms_gt', v)}
                            placeholder="e.g. 2000"
                        />
                    </LemonField.Pure>
                </>
            ) : null}
        </div>
    )
}
