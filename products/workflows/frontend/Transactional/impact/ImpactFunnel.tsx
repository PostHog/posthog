import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { emailImpactLogic } from './emailImpactLogic'
import { ImpactStep, stepBarPercents } from './impactSteps'
import { LinkTrackingPrompt } from './LinkTrackingPrompt'

export function ImpactFunnel({
    steps,
    showsLinkTrackingPrompt,
}: {
    steps: ImpactStep[]
    showsLinkTrackingPrompt: boolean
}): JSX.Element {
    const barPercents = stepBarPercents(steps)
    const promptSpansConversion =
        showsLinkTrackingPrompt && !!steps.find((step) => step.key === 'converted')?.missingFixedByEvent
    return (
        <ol className="m-0 p-0 list-none grid grid-cols-6 gap-2" data-attr="email-impact-funnel">
            {steps.map((step, index) => {
                if (showsLinkTrackingPrompt && step.key === 'session') {
                    return <LinkTrackingPrompt key={step.key} spansConversion={promptSpansConversion} />
                }
                if (promptSpansConversion && step.key === 'converted') {
                    return null
                }
                return (
                    <li key={step.key} className="flex flex-col gap-1 min-w-0">
                        <StepBar step={step} percent={barPercents[index]} />
                        <span className="text-xs text-secondary truncate" title={step.label}>
                            {step.label}
                        </span>
                        <StepValue step={step} />
                        <StepShare step={step} />
                    </li>
                )
            })}
        </ol>
    )
}

function StepBar({ step, percent }: { step: ImpactStep; percent: number | null }): JSX.Element {
    if (step.missingFixedByEvent) {
        return (
            <div className="h-28 rounded bg-surface-secondary flex items-center justify-center p-1">
                <FunnelEventPicker />
            </div>
        )
    }
    return (
        <div className="h-28 rounded bg-surface-secondary flex items-end overflow-hidden">
            {percent !== null && percent > 0 && (
                <div
                    data-attr={`email-impact-bar-${step.key}`}
                    className={step.key === 'converted' ? 'w-full bg-success' : 'w-full bg-accent'}
                    style={{ height: `${percent}%` }}
                />
            )}
        </div>
    )
}

function FunnelEventPicker(): JSX.Element {
    const { event } = useValues(emailImpactLogic)
    const { pickEvent } = useActions(emailImpactLogic)
    return (
        <TaxonomicPopover<string>
            size="small"
            type="secondary"
            className="max-w-full"
            truncate
            groupType={TaxonomicFilterGroupType.Events}
            groupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Events]}
            value={event ?? undefined}
            placeholder="Pick an event"
            onChange={(value) => pickEvent(value ? String(value) : null, 'funnel')}
            data-attr="email-impact-funnel-event"
        />
    )
}

function StepValue({ step }: { step: ImpactStep }): JSX.Element | null {
    if (step.value !== null) {
        return <span className="font-semibold text-base">{humanFriendlyNumber(step.value)}</span>
    }
    if (step.missingFixedByEvent) {
        return null
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
