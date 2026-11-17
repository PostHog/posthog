import clsx from 'clsx'

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
                    <StepBar step={step} sent={sent} />
                    <span className="text-xs text-secondary truncate" title={step.label}>
                        {step.label}
                    </span>
                    <StepValue step={step} />
                    <StepShare step={step} />
                </li>
            ))}
        </ol>
    )
}

function StepBar({ step, sent }: { step: ImpactStep; sent: number }): JSX.Element {
    return (
        <div className="h-28 rounded bg-surface-secondary flex items-end overflow-hidden">
            {step.value !== null && sent > 0 && (
                <div
                    className={step.key === 'converted' ? 'w-full bg-success' : 'w-full bg-accent'}
                    style={{ height: `${barPercent(step.value, sent)}%` }}
                />
            )}
        </div>
    )
}

function barPercent(value: number, sent: number): number {
    return value > 0 ? Math.max(MIN_VISIBLE_BAR_PERCENT, (value / sent) * 100) : 0
}

function StepValue({ step }: { step: ImpactStep }): JSX.Element {
    if (step.value !== null) {
        return <span className="font-semibold text-base">{humanFriendlyNumber(step.value)}</span>
    }
    return (
        <Explained detail={step.missingDetail} className="text-xs text-secondary">
            {step.missing}
        </Explained>
    )
}

function StepShare({ step }: { step: ImpactStep }): JSX.Element | null {
    if (step.share === null) {
        return null
    }
    return (
        <span className="text-xs text-secondary">
            <span>{percentage(step.share, 1)}</span>
            {step.shareOf && <Explained detail={step.shareDetail}>{` of ${step.shareOf}`}</Explained>}
        </span>
    )
}

function Explained({
    detail,
    className,
    children,
}: {
    detail?: string
    className?: string
    children: React.ReactNode
}): JSX.Element {
    if (!detail) {
        return <span className={className}>{children}</span>
    }
    return (
        <Tooltip title={detail}>
            <span tabIndex={0} className={clsx(className, 'underline decoration-dotted cursor-help')}>
                {children}
            </span>
        </Tooltip>
    )
}
