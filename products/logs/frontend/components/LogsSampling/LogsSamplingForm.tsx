import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { logsSamplingFormLogic } from './logsSamplingFormLogic'

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, simulation, simulationLoading, canSimulate, isLegacySeverityRule } =
        useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            {isLegacySeverityRule && (
                <LemonBanner type="warning">
                    This project still has a severity-based rule; it remains active in ingestion. To change severity
                    actions or thresholds, use the API or disable the rule here.
                </LemonBanner>
            )}
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
            {isLegacySeverityRule ? (
                <LemonField.Pure label="Rule type">
                    <LemonTag type="warning">Severity-based (legacy)</LemonTag>
                </LemonField.Pure>
            ) : null}
            {!isLegacySeverityRule ? (
                <>
                    <LemonField.Pure label="Scope: service name (optional)">
                        <LemonInput
                            value={samplingForm.scope_service}
                            onChange={(v) => setSamplingFormValue('scope_service', v)}
                            placeholder="Empty = all services"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Restrict to path (regex, optional)">
                        <LemonInput
                            value={samplingForm.scope_path_pattern}
                            onChange={(v) => setSamplingFormValue('scope_path_pattern', v)}
                            placeholder="Matched against url.path / http.route when present"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Attribute key (optional)"
                        help="Leave empty to use the default path-like attributes (http.route, url.path, …). When set, patterns match only this attribute’s string value."
                    >
                        <LemonInput
                            value={samplingForm.path_drop_match_attribute_key}
                            onChange={(v) => setSamplingFormValue('path_drop_match_attribute_key', v)}
                            placeholder="http.route"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Patterns to drop (regex, one per line)">
                        <LemonTextArea
                            value={samplingForm.path_drop_patterns}
                            onChange={(v) => setSamplingFormValue('path_drop_patterns', v)}
                            placeholder={'/healthz\n/metrics'}
                            rows={4}
                        />
                    </LemonField.Pure>
                </>
            ) : null}
        </div>
    )
}
