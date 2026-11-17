import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { ImpactStep } from './impactSteps'

/** Columns that shrink from sent to the conversion event, each scaled against sent. */
export function ImpactFunnel({ steps }: { steps: ImpactStep[] }): JSX.Element {
    const sent = steps[0].value ?? 0
    return (
        <ol className="m-0 p-0 list-none grid grid-cols-6 gap-2" data-attr="email-impact-funnel">
            {steps.map((step) => (
                <li key={step.key} className="flex flex-col gap-1 min-w-0">
                    <div className="h-28 rounded bg-surface-secondary flex items-end overflow-hidden">
                        {step.value !== null && sent > 0 && (
                            <div
                                className={step.key === 'converted' ? 'w-full bg-success' : 'w-full bg-accent'}
                                // A floor keeps a small non-zero step visible next to a large one.
                                style={{ height: `${step.value > 0 ? Math.max(2, (step.value / sent) * 100) : 0}%` }}
                            />
                        )}
                    </div>
                    <span className="text-xs text-secondary truncate" title={step.label}>
                        {step.label}
                    </span>
                    {step.value !== null ? (
                        <span className="font-semibold text-base">{humanFriendlyNumber(step.value)}</span>
                    ) : step.missingDetail ? (
                        <Tooltip title={step.missingDetail}>
                            <span className="text-xs text-secondary underline decoration-dotted cursor-help">
                                {step.missing}
                            </span>
                        </Tooltip>
                    ) : (
                        <span className="text-xs text-secondary">{step.missing}</span>
                    )}
                    {step.share !== null && (
                        <span className="text-xs text-secondary">
                            {percentage(step.share, 1)}
                            {step.shareOf ? ` of ${step.shareOf}` : ''}
                        </span>
                    )}
                </li>
            ))}
        </ol>
    )
}
