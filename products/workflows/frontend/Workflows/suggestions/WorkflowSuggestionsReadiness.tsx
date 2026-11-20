import clsx from 'clsx'
import { useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconClock } from '@posthog/icons'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { ReadinessStep, suggestionReadiness } from './suggestionReadiness'
import { workflowProposalsLogic } from './workflowProposalsLogic'

const STEP_STATE_LABELS: Record<ReadinessStep['state'], string> = {
    done: 'Done',
    waiting: 'In progress',
    blocked: 'Not started',
}

function StepIcon({ state }: { state: ReadinessStep['state'] }): JSX.Element {
    const Icon = state === 'done' ? IconCheckCircle : state === 'waiting' ? IconClock : IconCircleDashed
    return (
        <Icon
            className={clsx(
                'size-5 shrink-0',
                state === 'done' ? 'text-success' : state === 'waiting' ? 'text-secondary' : 'text-muted'
            )}
        />
    )
}

function StepProgress({ step }: { step: ReadinessStep }): JSX.Element | null {
    if (step.percent == null) {
        return null
    }
    return (
        <LemonProgress
            percent={step.percent}
            className="max-w-80"
            role="progressbar"
            aria-label={step.title}
            aria-valuenow={step.percent}
            aria-valuemin={0}
            aria-valuemax={100}
        />
    )
}

export function WorkflowSuggestionsReadiness({
    id,
    compact = false,
}: {
    id: string
    compact?: boolean
}): JSX.Element | null {
    const { optimization, turnOnDisabledReason } = useValues(workflowProposalsLogic({ id }))
    // A paused scout or one in dry run has its own notice, and a workflow that cannot turn suggestions on gets
    // no timeline it can never reach.
    const scoutCanFile = optimization?.scout_status === 'running' || optimization?.scout_status === 'not_running'
    if (!optimization || !scoutCanFile || (!optimization.enabled && turnOnDisabledReason)) {
        return null
    }
    const readiness = suggestionReadiness(optimization)
    if (!readiness) {
        return null
    }

    if (compact) {
        const sends = readiness.steps.find((step) => step.key === 'sends')
        return (
            <div className="flex flex-col gap-1 text-sm" data-attr="workflow-suggestions-readiness-compact">
                <span className="font-medium">{readiness.headline}</span>
                {sends ? <StepProgress step={sends} /> : null}
                {readiness.detail ? <span className="text-xs text-secondary">{readiness.detail}</span> : null}
            </div>
        )
    }

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-suggestions-readiness"
        >
            <div className="flex flex-col gap-0.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">
                    When to expect suggestions
                </span>
                <h3 className="mb-0 text-base font-semibold">{readiness.headline}</h3>
                {readiness.detail ? <p className="mb-0 text-sm text-secondary">{readiness.detail}</p> : null}
            </div>
            <ol className="m-0 flex list-none flex-col gap-3 p-0" role="list">
                {readiness.steps.map((step) => (
                    <li key={step.key} className="flex gap-2">
                        <StepIcon state={step.state} />
                        <div className="flex min-w-0 flex-1 flex-col gap-1">
                            <span className="text-sm font-medium">
                                <span className="sr-only">{STEP_STATE_LABELS[step.state]}: </span>
                                {step.title}
                            </span>
                            <StepProgress step={step} />
                            <span className="text-xs text-secondary">{step.detail}</span>
                        </div>
                    </li>
                ))}
            </ol>
        </div>
    )
}
