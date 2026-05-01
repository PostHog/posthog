import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingFormType, PathDropMatchTarget, SeverityActionChoice } from './logsSamplingFormLogic'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'
import { ruleTypeLabel } from './ruleTypeLabel'

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

const PATH_DROP_MATCH_TARGET_OPTIONS: { value: PathDropMatchTarget; label: string }[] = [
    { value: 'auto_path', label: 'Automatic path (http.route, url.path, …)' },
    { value: 'custom_attribute', label: 'One log attribute' },
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

    const pctKept = Math.round(Math.min(1, Math.max(0, rate)) * 100)

    return (
        <div className="grid grid-cols-[5.5rem_minmax(11rem,16rem)_minmax(0,1fr)] items-center gap-x-3 gap-y-1">
            <span className="text-muted text-sm">{label}</span>
            <LemonSelect
                options={ACTION_OPTIONS}
                value={action}
                onChange={(v) => v && setSamplingFormValue(actionKey, v)}
            />
            {action === 'sample' ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-muted shrink-0">Keep fraction</span>
                    <LemonInput
                        type="number"
                        min={0}
                        max={1}
                        step={0.05}
                        value={rate}
                        className="max-w-[7rem]"
                        onChange={(v) =>
                            setSamplingFormValue(rateKey, typeof v === 'number' ? v : parseFloat(String(v)) || 0)
                        }
                    />
                    <span className="text-sm text-muted tabular-nums whitespace-nowrap">≈{pctKept}% kept</span>
                </div>
            ) : (
                <div />
            )}
        </div>
    )
}

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors, simulation, simulationLoading, canSimulate, isNewRule } =
        useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isPathDrop = samplingForm.rule_type === RuleTypeEnumApi.PathDrop
    const isSeverity = samplingForm.rule_type === RuleTypeEnumApi.SeveritySampling

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
            <LemonField.Pure label="Name">
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
                    label="What should this rule do?"
                    info="You can create multiple rules; lower priority number runs first. The first rule that matches wins for each log line."
                    help={
                        <>
                            “Drop by severity” is for whole severity levels (info, warn, …). “Drop when matched” is for
                            regex on a path string or one attribute you pick. Optional{' '}
                            <strong>Sample (keep some)</strong> on severity keeps a fraction of traffic (see
                            per-severity help for trace vs no-trace behavior).
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
                label="Limit rule to matching path (optional)"
                info="If set, this rule only runs for log lines where this regex matches the automatic path string (first non-empty among url.path, http.path, http.route, path). Separate from “what your drop patterns match” below. Applies to severity rules too."
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
                        label="Drop patterns match on"
                        help="Choose what each regex line is compared to. Switching to automatic path clears the attribute key."
                        info="Automatic path uses the same path-like fields as the limit-to-path filter above. One log attribute tests only that field’s string (missing counts as empty)."
                    >
                        <LemonSelect<PathDropMatchTarget>
                            options={PATH_DROP_MATCH_TARGET_OPTIONS}
                            value={samplingForm.path_drop_match_target}
                            onChange={(v) => {
                                if (!v) {
                                    return
                                }
                                setSamplingFormValue('path_drop_match_target', v)
                                if (v === 'auto_path') {
                                    setSamplingFormValue('path_drop_match_attribute_key', '')
                                }
                            }}
                        />
                    </LemonField.Pure>
                    {samplingForm.path_drop_match_target === 'auto_path' ? (
                        <LemonBanner type="info">
                            <div className="text-sm">
                                <strong>Example:</strong> add lines{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">/healthz</code> and{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">/ready</code> — if{' '}
                                <em>any</em> pattern matches the log’s automatic path value, the line is dropped. Add a
                                limit above if you only want this under e.g.{' '}
                                <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">^/api/</code>.
                            </div>
                        </LemonBanner>
                    ) : (
                        <>
                            <LemonBanner type="info">
                                <div className="text-sm">
                                    <strong>Example:</strong> key{' '}
                                    <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">
                                        deployment.environment
                                    </code>
                                    , pattern line{' '}
                                    <code className="text-xs font-mono bg-bg-mid rounded px-1 py-0.5">^staging$</code> —
                                    only that attribute is tested (not the URL path).
                                </div>
                            </LemonBanner>
                            <LemonField.Pure
                                label="Log attribute key"
                                info="Exact OpenTelemetry attribute name as it appears on the log (copy from the log detail inspector)."
                                help="Not a property picker — type the key string."
                                error={samplingFormErrors.path_drop_match_attribute_key}
                            >
                                <LemonInput
                                    value={samplingForm.path_drop_match_attribute_key}
                                    onChange={(v) => setSamplingFormValue('path_drop_match_attribute_key', v)}
                                    placeholder="e.g. deployment.environment"
                                />
                            </LemonField.Pure>
                        </>
                    )}
                    <LemonField.Pure
                        label="Patterns to drop (regex, one per line)"
                        info={
                            samplingForm.path_drop_match_target === 'auto_path' ? (
                                <>
                                    Each line is a JavaScript-style regex tested against the automatic path string. If{' '}
                                    <strong>any</strong> line matches, the log is dropped. Invalid regex lines are
                                    skipped at ingestion.
                                </>
                            ) : (
                                <>
                                    Each line is a regex tested against the attribute value only. If{' '}
                                    <strong>any</strong> line matches, the log is dropped.
                                </>
                            )
                        }
                        help={
                            samplingForm.path_drop_match_target === 'auto_path'
                                ? 'Examples: /internal/ (substring), ^/api/v1/debug/ (prefix). Multiple lines are OR’d.'
                                : 'Examples: ^prod$, staging|dev. Multiple lines are OR’d.'
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
                    <LemonBanner type="info">
                        <div className="text-sm space-y-2">
                            <div>
                                <strong>Example — drop only noisy info logs:</strong> set <strong>Info</strong> to{' '}
                                <strong>Drop (not stored)</strong>, leave Debug / Warn / Error on <strong>Keep</strong>.
                                Every matching INFO line in scope is removed at ingestion; other levels pass through
                                unless another rule matches first.
                            </div>
                            <div>
                                <strong>Advanced:</strong> <strong>Sample (keep some)</strong> uses your rate as the
                                approximate share of traffic kept. With a <strong>trace ID</strong>, all lines in that
                                trace share one keep/drop coin flip at this severity (not “half the lines inside one
                                trace”). Without a trace ID, each line is decided on its own at random.
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
                        help="Keep fraction is 0–1 (e.g. 0.5 ≈ 50% of affected traffic stored). With a trace ID, every line in that trace gets the same keep/drop at this severity; without one, each line is random independently."
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
