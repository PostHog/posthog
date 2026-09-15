import { LemonTag } from '@posthog/lemon-ui'

import type { WorkflowProposalApi, WorkflowProposalOutcomeApi } from '../generated/api.schemas'
import { WorkflowMetricReading } from './WorkflowMetricReading'

export function WorkflowAppliedOutcome({
    proposal,
    outcome,
}: {
    proposal: WorkflowProposalApi
    outcome: WorkflowProposalOutcomeApi
}): JSX.Element {
    return (
        <div className="@container border rounded p-3 bg-surface-primary flex flex-col gap-2">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="font-semibold">{proposal.title}</span>
                <LemonTag type="success">Applied as version {proposal.applied_version}</LemonTag>
            </div>
            {/* Two windows side by side, not a controlled comparison. Said plainly so nobody reads a
                difference here as proof the change caused it. */}
            <p className="mb-0 text-secondary text-sm">
                Measured over {outcome.window}, before and after. Different periods, so treat a difference as a signal
                to look closer, not as proof.
            </p>
            {/* One column until there is room for two: at side-panel widths the pair would clip, and
                the scene hides horizontal overflow. */}
            <div className="grid grid-cols-1 @md:grid-cols-2 gap-3 text-sm">
                {(['before', 'after'] as const).map((side) => {
                    const reading = outcome[side]
                    return (
                        <div key={side} className="flex flex-col gap-1">
                            <span className="font-semibold">
                                {side === 'before' ? 'Before' : 'After'}
                                {reading ? ` (v${reading.version})` : ''}
                            </span>
                            {reading ? (
                                <>
                                    <WorkflowMetricReading reading={reading.target} />
                                    <WorkflowMetricReading reading={reading.click_through} />
                                    {reading.guardrails.map((guardrail) => (
                                        <WorkflowMetricReading key={guardrail.metric} reading={guardrail} />
                                    ))}
                                </>
                            ) : (
                                <span className="text-secondary">No data</span>
                            )}
                        </div>
                    )
                })}
            </div>
            {outcome.unavailable_guardrails.length > 0 && (
                <span className="text-xs text-secondary">
                    Not measured: {outcome.unavailable_guardrails.join(', ')}
                </span>
            )}
        </div>
    )
}
