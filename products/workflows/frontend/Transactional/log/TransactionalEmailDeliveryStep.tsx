import clsx from 'clsx'

import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DeliveryStep, gapLabel } from './emailDeliverySteps'

function StepDetail({ detail }: { detail: string }): JSX.Element {
    const text = <span className="text-xs text-secondary truncate">{detail}</span>
    return detail.length > 40 ? <Tooltip title={detail}>{text}</Tooltip> : text
}

function StepMarker({ state }: { state: DeliveryStep['state'] }): JSX.Element {
    return (
        <span
            className={clsx(
                'flex items-center justify-center size-6 rounded-full shrink-0 border',
                state === 'done' && 'bg-success border-success text-white',
                state === 'failed' && 'bg-danger border-danger text-white',
                state === 'pending' && 'bg-surface-primary border-dashed border-border-bold',
                state === 'untracked' && 'bg-surface-secondary border-border text-tertiary'
            )}
        >
            {state === 'done' && <IconCheck className="size-4" />}
            {state === 'failed' && <IconX className="size-4" />}
            {state === 'untracked' && <IconMinus className="size-4" />}
        </span>
    )
}

function isNotReached(state: DeliveryStep['state']): boolean {
    return state === 'pending' || state === 'untracked'
}

function StepWhen({ step }: { step: DeliveryStep }): JSX.Element | null {
    if (step.at) {
        const gap = gapLabel(step.at, step.previousAt)
        return (
            <span className="text-xs text-secondary flex flex-wrap gap-x-1">
                <TZLabel time={step.at} formatDate="MMM D" formatTime="HH:mm:ss" />
                {gap && <span>· {gap}</span>}
            </span>
        )
    }
    if (step.state === 'untracked') {
        return (
            <Tooltip
                title={
                    step.key === 'opened'
                        ? 'Open tracking was off for this send, so it records no opens.'
                        : 'Click tracking was off for this send, so it records no clicks.'
                }
                openOnClick
            >
                <span tabIndex={0} className="text-xs text-secondary" data-attr="transactional-email-not-tracked">
                    Not tracked
                </span>
            </Tooltip>
        )
    }
    if (step.state === 'pending') {
        return (
            <span className="text-xs text-secondary">
                {step.key === 'opened' || step.key === 'clicked' ? 'Not yet' : 'Waiting'}
            </span>
        )
    }
    return null
}

/** One step of the delivery progress, and the line that leads to the next step. */
export function TransactionalEmailDeliveryStep({
    step,
    next,
}: {
    step: DeliveryStep
    next: DeliveryStep | undefined
}): JSX.Element {
    return (
        <li className="flex @2xl:flex-col gap-3 @2xl:gap-2 flex-1 min-w-0">
            <div className="flex items-center @2xl:w-full">
                <StepMarker state={step.state} />
                {next && (
                    <span
                        className={clsx(
                            'hidden @2xl:block h-px flex-1 mx-2',
                            isNotReached(next.state) ? 'bg-border' : 'bg-border-bold'
                        )}
                    />
                )}
            </div>
            <div className="flex flex-col min-w-0 @2xl:pr-4">
                <span
                    className={clsx(
                        'text-sm font-semibold',
                        isNotReached(step.state) && 'text-secondary',
                        step.state === 'failed' && 'text-danger'
                    )}
                >
                    {step.label}
                </span>
                <StepWhen step={step} />
                {step.detail && step.state !== 'failed' && <StepDetail detail={step.detail} />}
            </div>
        </li>
    )
}
