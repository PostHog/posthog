import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { ImpactStep } from './impactSteps'

const MIN_VISIBLE_BAR_PERCENT = 2

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
                                style={{
                                    height: `${step.value > 0 ? Math.max(MIN_VISIBLE_BAR_PERCENT, (step.value / sent) * 100) : 0}%`,
                                }}
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
                            <span
                                tabIndex={0}
                                className="text-xs text-secondary underline decoration-dotted cursor-help"
                            >
                                {step.missing}
                            </span>
                        </Tooltip>
                    ) : (
                        <span className="text-xs text-secondary">{step.missing}</span>
                    )}
                    {step.share !== null && (
                        <span className="text-xs text-secondary">
                            <span>{percentage(step.share, 1)}</span>
                            {step.shareOf && step.shareDetail ? (
                                <Tooltip title={step.shareDetail}>
                                    <span tabIndex={0} className="underline decoration-dotted cursor-help">
                                        {` of ${step.shareOf}`}
                                    </span>
                                </Tooltip>
                            ) : step.shareOf ? (
                                <span>{` of ${step.shareOf}`}</span>
                            ) : null}
                        </span>
                    )}
                </li>
            ))}
        </ol>
    )
}
