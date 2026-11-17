// PROTOTYPE (ticket #385), throwaway. The path from sent to the conversion event, for one email across all its sends,
// drawn as a funnel. Any event can be the conversion; the funnel rebuilds around it.
import { Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { ImpactData, percent } from './impactFixtures'
import { useEmailJourneyPrototype } from './useEmailJourneyPrototype'

interface Step {
    label: string
    value: number | null
    /** Why the value is missing, shown in its place. */
    missing?: string
    missingDetail?: string
    /** The step its percentage is taken of, when not the one before. */
    of?: number
}

export const LINK_TAG_DETAIL =
    'PostHog follows a click into your product through a tag it adds to links on your sending domain. Link tagging is rolling out and is not on for this project yet. Conversions still count, because they go through the person on each send.'

export function impactSteps(data: ImpactData): Step[] {
    const notTracked = data.clicked === null
    return [
        { label: 'Sent', value: data.sent },
        { label: 'Delivered', value: data.delivered },
        { label: 'Opened', value: data.opened, missing: 'Not tracked' },
        { label: 'Clicked', value: data.clicked, missing: 'Not tracked' },
        {
            label: 'Started a session',
            value: data.landed,
            missing: notTracked ? 'Not tracked' : 'Needs link tagging',
            missingDetail: notTracked ? undefined : LINK_TAG_DETAIL,
        },
        {
            label: data.goal ? data.goal.event : 'Converted',
            value: data.converted,
            missing: 'Pick an event',
            of: notTracked ? 1 : 3,
        },
    ]
}

/** The conversion event leads the page: pick any event, and the funnel ends with it. */
export function GoalPicker({ data }: { data: ImpactData }): JSX.Element {
    const { set } = useEmailJourneyPrototype()
    return (
        <span className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">Counts as converted</span>
            <TaxonomicPopover<string>
                size="small"
                type="secondary"
                groupType={TaxonomicFilterGroupType.Events}
                groupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Events]}
                value={data.goal?.event ?? null}
                placeholder="Pick any event"
                onChange={(value) => set({ goal: value ? String(value) : null, case: null })}
                data-attr="prototype-impact-goal"
            />
            {data.goal && (
                <span className="text-secondary text-sm">
                    within {data.goal.windowDays} days of the {data.clicked === null ? 'send' : 'click'}
                </span>
            )}
        </span>
    )
}

export function ImpactLift({ data }: { data: ImpactData }): JSX.Element | null {
    if (!data.goal || data.converted === null) {
        return null
    }
    if (data.clicked === null) {
        return (
            <p className="text-sm m-0">
                {percent(data.converted, data.delivered)} of recipients did <strong>{data.goal.event}</strong> within{' '}
                {data.goal.windowDays} days of the send. Without click tracking, PostHog can't tell whether the email
                led there.
            </p>
        )
    }
    return (
        <p className="text-sm m-0">
            <strong>{percent(data.converted, data.clicked)}</strong> of people who clicked did{' '}
            <strong>{data.goal.event}</strong> within {data.goal.windowDays} days
            {data.convertedWithoutClick && (
                <>
                    , against{' '}
                    <strong>{percent(data.convertedWithoutClick.people, data.convertedWithoutClick.of)}</strong> of
                    recipients who didn't click
                </>
            )}
            .{' '}
            <Tooltip title="People who click were often more likely to convert anyway, so read this as a signal, not a cause.">
                <span className="text-secondary underline decoration-dotted cursor-help">How to read this</span>
            </Tooltip>
        </p>
    )
}

/** Columns that shrink from sent to the conversion event, like a funnel insight. */
export function ImpactFunnel({ data }: { data: ImpactData }): JSX.Element {
    const steps = impactSteps(data)
    return (
        <ol className="m-0 p-0 list-none grid grid-cols-6 gap-2" data-attr="prototype-impact-funnel">
            {steps.map((step, index) => {
                const base = index > 0 ? steps[step.of ?? index - 1] : null
                return (
                    <li key={step.label} className="flex flex-col gap-1 min-w-0">
                        <div className="h-28 rounded bg-surface-secondary flex items-end overflow-hidden">
                            {step.value !== null && (
                                <div
                                    className={`w-full ${index === steps.length - 1 ? 'bg-success' : 'bg-accent'}`}
                                    style={{ height: `${Math.max(2, (step.value / data.sent) * 100)}%` }}
                                />
                            )}
                        </div>
                        <span className="text-xs text-secondary truncate" title={step.label}>
                            {step.label}
                        </span>
                        <StepValue step={step} />
                        {step.value !== null && base?.value ? (
                            <span className="text-xs text-secondary">
                                {percent(step.value, base.value)}
                                {step.of !== undefined ? ` of ${base.label.toLowerCase()}` : ''}
                            </span>
                        ) : null}
                    </li>
                )
            })}
        </ol>
    )
}

function StepValue({ step }: { step: Step }): JSX.Element {
    if (step.value !== null) {
        return <span className="font-semibold text-base">{humanFriendlyNumber(step.value)}</span>
    }
    const missing = <span className="text-xs text-secondary">{step.missing}</span>
    return step.missingDetail ? (
        <Tooltip title={step.missingDetail}>
            <span className="underline decoration-dotted cursor-help">{missing}</span>
        </Tooltip>
    ) : (
        missing
    )
}
