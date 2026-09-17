import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import {
    MIN_EVIDENCE_SAMPLE,
    describeWindow,
    evidenceDisagrees,
    formatValue,
    readGuardrails,
    readMeasured,
    readUnit,
} from './suggestionEvidence'

export function WorkflowSuggestionEvidence({ evidence }: { evidence: Record<string, unknown> }): JSX.Element | null {
    const metric = typeof evidence.metric === 'string' ? evidence.metric : null
    if (!metric) {
        return null
    }
    const unit = readUnit(evidence.unit)
    const current = formatValue(evidence.current_value, unit)
    const target = formatValue(evidence.target_value, unit)
    const window = typeof evidence.window === 'string' ? evidence.window : null
    const sample = typeof evidence.n === 'number' ? evidence.n : null
    const measured = readMeasured(evidence)

    if (measured) {
        const measuredValue = formatValue(measured.target.value, 'rate')
        return (
            <div className="flex flex-col gap-1 text-sm">
                <span className="flex items-center gap-2 flex-wrap">
                    <span>
                        {measured.target.metric} {measuredValue ?? 'no data'} on {measured.target.n} tracked sends (v
                        {measured.version}, {describeWindow(measured.window)}){target ? `, target ${target}` : ''}
                    </span>
                    <Tooltip title="PostHog read this step's metrics itself when the suggestion was filed.">
                        <LemonTag type="success">Measured by PostHog</LemonTag>
                    </Tooltip>
                    {measured.target.below_minimum_sample && (
                        <Tooltip
                            title={`Under ${MIN_EVIDENCE_SAMPLE} sends. Treat this as a hunch to check, not a finding.`}
                        >
                            <LemonTag type="warning">Too little data</LemonTag>
                        </Tooltip>
                    )}
                </span>
                {measured.guardrails.length > 0 && (
                    <span className="text-secondary">
                        Alongside:{' '}
                        {measured.guardrails
                            .map(
                                (guardrail) =>
                                    `${guardrail.metric} ${formatValue(guardrail.value, 'rate') ?? 'no data'}`
                            )
                            .join(', ')}
                    </span>
                )}
                {evidenceDisagrees(evidence, measured) && (
                    <span className="text-warning">
                        The scout reported {current ?? 'no value'}
                        {sample !== null ? ` on ${sample}` : ''}, which is not what PostHog measured. Read its reasoning
                        with that in mind.
                    </span>
                )}
            </div>
        )
    }

    const guardrails = readGuardrails(evidence)
    const lowSample = sample !== null && sample < MIN_EVIDENCE_SAMPLE

    return (
        <div className="flex flex-col gap-1 text-sm">
            <span className="flex items-center gap-2 flex-wrap">
                <span>
                    {metric}: {current ?? 'no data'}
                    {target ? `, target ${target}` : ''}
                    {window ? ` over ${window}` : ''}
                    {sample !== null ? ` (${sample} observations)` : ''}
                </span>
                <Tooltip title="These numbers came from the producer. PostHog could not read the step's metrics when this was filed, so check them on the Metrics tab before deciding.">
                    <LemonTag type="warning">Unverified</LemonTag>
                </Tooltip>
                {sample === null && (
                    <Tooltip title="This suggestion did not say how many observations its number came from, so there is no way to tell a result from noise.">
                        <LemonTag type="warning">No sample size</LemonTag>
                    </Tooltip>
                )}
                {lowSample && (
                    <Tooltip
                        title={`Under ${MIN_EVIDENCE_SAMPLE} observations. Treat this as a hunch to check, not a finding.`}
                    >
                        <LemonTag type="warning">Too little data</LemonTag>
                    </Tooltip>
                )}
            </span>
            {guardrails.length > 0 && (
                <span className="text-secondary">
                    Alongside:{' '}
                    {guardrails
                        .map(
                            (guardrail) =>
                                `${guardrail.metric} ${formatValue(guardrail.value, readUnit(guardrail.unit)) ?? 'no data'}`
                        )
                        .join(', ')}
                </span>
            )}
        </div>
    )
}
