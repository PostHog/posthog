import clsx from 'clsx'
import { useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconClock } from '@posthog/icons'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { ReadinessStep, suggestionReadiness } from './suggestionReadiness'
import { workflowProposalsLogic } from './workflowProposalsLogic'

function StepIcon({ state }: { state: ReadinessStep['state'] }): JSX.Element {
    if (state === 'done') {
        return <IconCheckCircle className="size-5 shrink-0 text-success" />
    }
    if (state === 'waiting') {
        return <IconClock className="size-5 shrink-0 text-warning" />
    }
    return <IconCircleDashed className="size-5 shrink-0 text-muted" />
}

export function WorkflowSuggestionsReadiness({
    id,
    compact = false,
}: {
    id: string
    compact?: boolean
}): JSX.Element | null {
    const { optimization } = useValues(workflowProposalsLogic({ id }))
    const readiness = suggestionReadiness(optimization)
    if (!readiness) {
        return null
    }

    if (compact) {
        const sends = readiness.steps.find((step) => step.key === 'sends')
        return (
            <div className="flex flex-col gap-1 text-sm" data-attr="workflow-suggestions-readiness-compact">
                <span className="font-medium">{readiness.headline}</span>
                {sends?.percent != null ? (
                    <LemonProgress percent={sends.percent} strokeColor="var(--warning)" className="max-w-60" />
                ) : null}
                {readiness.detail ? <span className="text-xs text-muted">{readiness.detail}</span> : null}
            </div>
        )
    }

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-suggestions-readiness"
        >
            <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                    When to expect suggestions
                </span>
                <h3 className="mb-0 text-base font-semibold">{readiness.headline}</h3>
                {readiness.detail ? <p className="mb-0 text-sm text-secondary">{readiness.detail}</p> : null}
            </div>
            <ol className="m-0 flex list-none flex-col gap-3 p-0">
                {readiness.steps.map((step) => (
                    <li key={step.key} className="flex gap-2">
                        <StepIcon state={step.state} />
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className={clsx('text-sm font-medium', step.state === 'blocked' && 'text-muted')}>
                                {step.title}
                            </span>
                            {step.percent != null ? (
                                <LemonProgress
                                    percent={step.percent}
                                    strokeColor="var(--warning)"
                                    className="max-w-80"
                                />
                            ) : null}
                            <span className="text-xs text-secondary">{step.detail}</span>
                        </div>
                    </li>
                ))}
            </ol>
        </div>
    )
}
