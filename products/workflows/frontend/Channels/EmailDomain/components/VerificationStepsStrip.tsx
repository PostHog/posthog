import clsx from 'clsx'

import { IconCheck, IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { VerificationStep } from '../emailDomainLogic'

const STATE_ICON: Record<VerificationStep['state'], JSX.Element> = {
    done: <IconCheck className="text-success" />,
    active: <Spinner className="text-sm" />,
    todo: <span className="w-2 h-2 rounded-full border border-primary" />,
    stuck: <IconWarning className="text-danger" />,
}

export function VerificationStepsStrip({ steps }: { steps: VerificationStep[] }): JSX.Element {
    return (
        <ol className="m-0 p-0 list-none grid @md:grid-cols-3 gap-2 text-sm" aria-label="Verification steps">
            {steps.map((step) => (
                <li
                    key={step.key}
                    className={clsx(
                        'flex items-start gap-2 rounded border p-2.5 min-w-0',
                        step.state === 'done' && 'bg-success-highlight border-success',
                        step.state === 'active' && 'bg-accent-highlight-secondary border-accent',
                        step.state === 'stuck' && 'bg-danger-highlight border-danger',
                        step.state === 'todo' && 'bg-surface-secondary'
                    )}
                >
                    <span className="shrink-0 w-5 h-5 inline-flex items-center justify-center">
                        {STATE_ICON[step.state]}
                    </span>
                    <span className="flex flex-col min-w-0">
                        <span className={clsx('font-medium', step.state === 'todo' && 'text-secondary')}>
                            {step.label}
                        </span>
                        <span className="text-xs text-secondary">{step.detail}</span>
                    </span>
                </li>
            ))}
        </ol>
    )
}
