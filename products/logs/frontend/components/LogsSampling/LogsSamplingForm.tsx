import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsSamplingFormType, SeverityActionChoice } from './logsSamplingFormLogic'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const RULE_TYPE_OPTIONS = [
    { value: RuleTypeEnumApi.SeveritySampling, label: 'Severity sampling' },
    { value: RuleTypeEnumApi.PathDrop, label: 'Path drop' },
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

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, simulation, simulationLoading, canSimulate } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
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
                    placeholder="e.g. Sample noisy info logs"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Enabled">
                <LemonSwitch checked={samplingForm.enabled} onChange={(v) => setSamplingFormValue('enabled', v)} />
            </LemonField.Pure>
            <LemonField.Pure label="Rule type">
                <LemonSelect
                    options={RULE_TYPE_OPTIONS}
                    value={samplingForm.rule_type}
                    onChange={(v) => v && setSamplingFormValue('rule_type', v as LogsSamplingFormType['rule_type'])}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Scope: service name (optional)">
                <LemonInput
                    value={samplingForm.scope_service}
                    onChange={(v) => setSamplingFormValue('scope_service', v)}
                    placeholder="Empty = all services"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Scope: path regex (optional)">
                <LemonInput
                    value={samplingForm.scope_path_pattern}
                    onChange={(v) => setSamplingFormValue('scope_path_pattern', v)}
                    placeholder="Matched against url.path / http.route when present"
                />
            </LemonField.Pure>
            {samplingForm.rule_type === RuleTypeEnumApi.PathDrop && (
                <LemonField.Pure label="Path patterns to drop (one regex per line)">
                    <LemonTextArea
                        value={samplingForm.path_drop_patterns}
                        onChange={(v) => setSamplingFormValue('path_drop_patterns', v)}
                        placeholder={'/healthz\n/metrics'}
                        rows={4}
                    />
                </LemonField.Pure>
            )}
            {samplingForm.rule_type === RuleTypeEnumApi.SeveritySampling && (
                <>
                    <div className="font-semibold">Severity actions</div>
                    <SeverityRow label="Debug" actionKey="severity_debug" rateKey="severity_debug_rate" />
                    <SeverityRow label="Info" actionKey="severity_info" rateKey="severity_info_rate" />
                    <SeverityRow label="Warn" actionKey="severity_warn" rateKey="severity_warn_rate" />
                    <SeverityRow label="Error" actionKey="severity_error" rateKey="severity_error_rate" />
                    <div className="font-semibold mt-2">Always keep (optional)</div>
                    <LemonField.Pure label="HTTP status >=" className="max-w-xs">
                        <LemonInput
                            value={samplingForm.always_keep_status_gte}
                            onChange={(v) => setSamplingFormValue('always_keep_status_gte', v)}
                            placeholder="e.g. 500"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Latency greater than (ms)" className="max-w-xs">
                        <LemonInput
                            value={samplingForm.always_keep_latency_ms_gt}
                            onChange={(v) => setSamplingFormValue('always_keep_latency_ms_gt', v)}
                            placeholder="e.g. 2000"
                        />
                    </LemonField.Pure>
                </>
            )}
        </div>
    )
}
