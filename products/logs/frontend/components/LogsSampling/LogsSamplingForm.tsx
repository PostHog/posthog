import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingFormType, SeverityActionChoice } from './logsSamplingFormLogic'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const RULE_TYPE_OPTIONS_CREATE: { value: RuleTypeEnumApi; label: string }[] = [
    {
        value: RuleTypeEnumApi.PathDrop,
        label: 'Drop when matched (regex on path or attribute)',
    },
    {
        value: RuleTypeEnumApi.SeveritySampling,
        label: 'Drop by severity',
    },
]

const ACTION_OPTIONS: { value: SeverityActionChoice; label: string }[] = [
    { value: 'keep', label: 'Keep' },
    { value: 'drop', label: 'Drop (not stored)' },
    { value: 'sample', label: 'Sample (keep some)' },
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
        return 'Drop by severity'
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
                    help={
                        <>
                            “Drop by severity” is for whole severity levels (info, warn, …). “Drop when matched” is for
                            regex on a path string or one attribute you pick. Optional{' '}
                            <strong>Sample (keep some)</strong> on severity only reduces volume while keeping a random
                            subset per trace.
                        </>
                    }
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
            <p className="text-secondary text-xs -mt-2">
                Grey text under fields is always visible. The <span className="text-secondary font-semibold">ⓘ</span>{' '}
                beside a label opens more detail on hover.
            </p>
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
                    <LemonBanner type="info">
                        <div className="text-sm space-y-2">
                            <div>
                                <strong>Example — drop health checks (default path):</strong> leave “Attribute key”
                                empty. Patterns{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">/healthz</code> and{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">/ready</code> — if{' '}
                                <em>any</em> line matches the log’s path-like value (first of{' '}
                                <code className="text-xs font-mono">url.path</code>,{' '}
                                <code className="text-xs font-mono">http.path</code>,{' '}
                                <code className="text-xs font-mono">http.route</code>,{' '}
                                <code className="text-xs font-mono">path</code>), the whole log line is dropped.
                            </div>
                            <div>
                                <strong>Example — drop by custom attribute:</strong> attribute key{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">
                                    deployment.environment
                                </code>
                                , pattern{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">^staging$</code> —
                                only that attribute’s string is tested (not the URL). One key per rule; combine scopes
                                with separate rules if needed.
                            </div>
                        </div>
                    </LemonBanner>
                    <LemonField.Pure
                        label="Attribute key (optional)"
                        info="Not a dropdown: type the exact OpenTelemetry log attribute name (same string as in your SDK / collector). Empty = use PostHog’s built-in path-like attributes in order: url.path, http.path, http.route, path."
                        help="This is the single string field your regex lines are tested against. It is not a property picker—copy the key from your logs (e.g. http.route) or leave empty for automatic path matching."
                    >
                        <LemonInput
                            value={samplingForm.path_drop_match_attribute_key}
                            onChange={(v) => setSamplingFormValue('path_drop_match_attribute_key', v)}
                            placeholder="Leave empty for path — or e.g. http.route"
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
                        help="Example lines: /internal/ (substring), ^/api/v1/debug/ (prefix), .*noise.* (broad — use carefully). OR across lines: first matching pattern wins the drop."
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
                    <LemonBanner type="info">
                        <div className="text-sm space-y-2">
                            <div>
                                <strong>Example — drop only noisy info logs:</strong> set <strong>Info</strong> to{' '}
                                <strong>Drop (not stored)</strong>, leave Debug / Warn / Error on <strong>Keep</strong>.
                                Every matching INFO line in scope is removed at ingestion; other levels pass through
                                unless another rule matches first.
                            </div>
                            <div>
                                <strong>Advanced:</strong> <strong>Sample (keep some)</strong> keeps a stable random
                                fraction per trace (same trace → same decision). Use when you still want some lines at
                                that severity in PostHog.
                            </div>
                        </div>
                    </LemonBanner>
                    <LemonBanner type="warning">
                        <strong>Drop</strong> and <strong>Sample (keep some)</strong> both remove data from storage for
                        affected lines; only <strong>Keep</strong> leaves that severity unchanged for this rule.
                    </LemonBanner>
                    <LemonField.Pure
                        label="Per severity level"
                        info="Evaluated after scope (service + path filter above). Ordinals follow OpenTelemetry severity on the log line (debug, info, warn, error)."
                    >
                        <div className="flex flex-col gap-2">
                            <SeverityRow label="Debug" actionKey="severity_debug" rateKey="severity_debug_rate" />
                            <SeverityRow label="Info" actionKey="severity_info" rateKey="severity_info_rate" />
                            <SeverityRow label="Warn" actionKey="severity_warn" rateKey="severity_warn_rate" />
                            <SeverityRow label="Error" actionKey="severity_error" rateKey="severity_error_rate" />
                        </div>
                    </LemonField.Pure>
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
