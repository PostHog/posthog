import clsx from 'clsx'

import { IconCheck } from '@posthog/icons'

import { EmailDomainPhase } from '../emailDomainLogic'

const STEPS: { label: string; phases: EmailDomainPhase[] }[] = [
    { label: 'Domain', phases: ['domain'] },
    { label: 'Settings', phases: ['loading', 'unavailable', 'settings', 'verifying'] },
    { label: 'Ready', phases: ['ready'] },
]

export function StepIndicator({ phase }: { phase: EmailDomainPhase }): JSX.Element {
    const currentIndex = STEPS.findIndex((step) => step.phases.includes(phase))
    return (
        <ol className="m-0 p-0 list-none flex items-center justify-center gap-2 text-xs" aria-label="Setup steps">
            {STEPS.map((step, index) => {
                const done = index < currentIndex
                const current = index === currentIndex
                return (
                    <li key={step.label} className="flex items-center gap-2">
                        {index > 0 && (
                            <span
                                className={clsx('w-6 border-t', done || current ? 'border-accent' : 'border-primary')}
                            />
                        )}
                        <span
                            className={clsx(
                                'inline-flex items-center justify-center w-5 h-5 rounded-full border font-semibold',
                                done && 'bg-success-highlight border-success text-success',
                                current && 'bg-accent text-white border-accent',
                                !done && !current && 'border-primary text-muted'
                            )}
                            aria-current={current ? 'step' : undefined}
                        >
                            {done ? <IconCheck /> : index + 1}
                        </span>
                        <span className={clsx(current ? 'font-semibold text-primary' : 'text-secondary')}>
                            {step.label}
                        </span>
                    </li>
                )
            })}
        </ol>
    )
}
