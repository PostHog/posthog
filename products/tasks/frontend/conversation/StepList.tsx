import { IconCheckCircle, IconCircleDashed, IconSpinner, IconX } from '@posthog/icons'
import { JSX } from 'react'

/**
 * Ported from apps/code/src/renderer/components/ui/StepList.tsx.
 *
 * The Step / StepStatus shapes are identical to the reference; only the icons
 * and layout primitives are swapped for PostHog-native ones (@posthog/icons +
 * Tailwind instead of phosphor + Radix).
 */

export type StepStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface Step {
    key: string
    label: string
    status: StepStatus
    detail?: string
}

interface StepIconProps {
    status: StepStatus
    size?: number
}

export function StepIcon({ status, size = 14 }: StepIconProps): JSX.Element {
    const style = { fontSize: size }
    switch (status) {
        case 'in_progress':
            return <IconSpinner className="animate-spin text-accent" style={style} />
        case 'completed':
            return <IconCheckCircle className="text-success" style={style} />
        case 'failed':
            return <IconX className="text-danger" style={style} />
        default:
            return <IconCircleDashed className="text-muted" style={style} />
    }
}

interface StepRowProps {
    step: Step
    size?: '1' | '2'
}

function StepRow({ step, size = '2' }: StepRowProps): JSX.Element {
    const sizeClass = size === '1' ? 'text-[13px]' : 'text-sm'
    return (
        <div className="flex flex-col gap-0">
            <div className="flex items-center gap-2">
                <StepIcon status={step.status} />
                <span className={`${sizeClass} text-default`}>{step.label}</span>
            </div>
            {step.detail && (
                <div className="pl-5">
                    <span className="text-[13px] text-muted">{step.detail}</span>
                </div>
            )}
        </div>
    )
}

interface StepListProps {
    steps: Step[]
    /** Text size for step labels. Default "2". */
    size?: '1' | '2'
    /** Gap between step rows (Tailwind gap step). Default "1". */
    gap?: '1' | '2' | '3'
}

export function StepList({ steps, size = '2', gap = '1' }: StepListProps): JSX.Element {
    const gapClass = gap === '3' ? 'gap-3' : gap === '2' ? 'gap-2' : 'gap-1'
    return (
        <div className={`flex flex-col ${gapClass}`}>
            {steps.map((step) => (
                <StepRow key={step.key} step={step} size={size} />
            ))}
        </div>
    )
}
