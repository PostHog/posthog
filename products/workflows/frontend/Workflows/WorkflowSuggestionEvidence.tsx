import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { MIN_EVIDENCE_SAMPLE, formatValue, readGuardrails } from './suggestionEvidence'

export function WorkflowSuggestionEvidence({ evidence }: { evidence: Record<string, unknown> }): JSX.Element | null {
    const metric = typeof evidence.metric === 'string' ? evidence.metric : null
    if (!metric) {
        return null
    }
    const current = formatValue(evidence.current_value)
    const target = formatValue(evidence.target_value)
    const window = typeof evidence.window === 'string' ? evidence.window : null
    const sample = typeof evidence.n === 'number' ? evidence.n : null
    const guardrails = readGuardrails(evidence)
    const unavailable = Array.isArray(evidence.guardrails_unavailable)
        ? evidence.guardrails_unavailable.filter((name): name is string => typeof name === 'string')
        : []
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
                        .map((guardrail) => `${guardrail.metric} ${formatValue(guardrail.value) ?? 'no data'}`)
                        .join(', ')}
                    {unavailable.length > 0 ? `. Not measured: ${unavailable.join(', ')}` : ''}
                </span>
            )}
            {guardrails.length === 0 && (
                <Tooltip title="No counter-metrics were sent with this suggestion, so a change that lifts the target by harming something else would not show here.">
                    <LemonTag type="warning">No counter-metrics</LemonTag>
                </Tooltip>
            )}
        </div>
    )
}
