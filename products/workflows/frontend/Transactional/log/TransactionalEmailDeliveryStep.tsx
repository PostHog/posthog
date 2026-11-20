import clsx from 'clsx'

import { IconCheck, IconInfo, IconMinus, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DeliveryStep, gapLabel } from './emailDeliverySteps'

const NOT_TRACKED_EXPLANATION =
    "Links in sensitive emails aren't tracked, because they can contain login codes or reset tokens. Older sends of this template can still record clicks."

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

function NotTrackedNote(): JSX.Element {
    return (
        <span className="text-xs text-secondary flex items-center gap-1">
            Not tracked
            <Tooltip title={NOT_TRACKED_EXPLANATION} openOnClick>
                <button
                    type="button"
                    aria-label={NOT_TRACKED_EXPLANATION}
                    className="inline-flex cursor-help text-sm"
                    data-attr="transactional-email-clicks-not-tracked"
                >
                    <IconInfo />
                </button>
            </Tooltip>
        </span>
    )
}

/** One step of the delivery progress, and the line that leads to the next step. */
export function TransactionalEmailDeliveryStep({
    step,
    next,
}: {
    step: DeliveryStep
    next: DeliveryStep | undefined
}): JSX.Element {
    const gap = step.at ? gapLabel(step.at, step.previousAt) : null
    return (
        <li className="flex @2xl:flex-col gap-3 @2xl:gap-2 flex-1 min-w-0">
            <div className="flex items-center @2xl:w-full">
                <StepMarker state={step.state} />
                {next && (
                    <span
                        className={clsx(
                            'hidden @2xl:block h-px flex-1 mx-2',
                            next.state === 'pending' || next.state === 'untracked' ? 'bg-border' : 'bg-border-bold'
                        )}
                    />
                )}
            </div>
            <div className="flex flex-col min-w-0 @2xl:pr-4">
                <span
                    className={clsx(
                        'text-sm font-semibold',
                        (step.state === 'pending' || step.state === 'untracked') && 'text-secondary',
                        step.state === 'failed' && 'text-danger'
                    )}
                >
                    {step.label}
                </span>
                {step.at ? (
                    <span className="text-xs text-secondary flex flex-wrap gap-x-1">
                        <TZLabel time={step.at} formatDate="MMM D" formatTime="HH:mm:ss" />
                        {gap && <span>· {gap}</span>}
                    </span>
                ) : (
                    step.state === 'pending' && (
                        <span className="text-xs text-secondary">
                            {step.key === 'opened' || step.key === 'clicked' ? 'Not yet' : 'Waiting'}
                        </span>
                    )
                )}
                {step.state === 'untracked' && <NotTrackedNote />}
                {step.detail && step.state !== 'failed' && <StepDetail detail={step.detail} />}
            </div>
        </li>
    )
}
