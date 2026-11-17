// PROTOTYPE (ticket #385), throwaway. The path from sent to the conversion event, for one email across all its sends.
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { GOAL_OPTIONS, ImpactData, percent } from './impactFixtures'
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
            of: 3,
        },
    ]
}

export function GoalPicker({ data }: { data: ImpactData }): JSX.Element {
    const { set } = useEmailJourneyPrototype()
    return (
        <span className="flex items-center gap-2 text-sm">
            <span className="text-secondary">Counts as converted</span>
            <LemonSelect
                size="small"
                placeholder="Pick an event"
                value={data.goal?.event ?? null}
                onChange={() => set({ case: null })}
                options={GOAL_OPTIONS.map((event) => ({ value: event, label: event }))}
                data-attr="prototype-impact-goal"
            />
            {data.goal && (
                <span className="text-secondary">
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

export function ImpactFunnel({ data, layout }: { data: ImpactData; layout: 'bars' | 'list' | 'strip' }): JSX.Element {
    const steps = impactSteps(data)
    const values = (index: number): number | null => steps[index].value

    if (layout === 'strip') {
        return (
            <div className="flex flex-wrap items-stretch border rounded bg-surface-primary divide-x">
                {steps.map((step, index) => {
                    const of = step.of ?? index - 1
                    return (
                        <div key={step.label} className="flex-1 min-w-32 px-4 py-2 flex flex-col">
                            <span className="text-xs text-secondary">{step.label}</span>
                            <StepValue step={step} />
                            {step.value !== null && index > 0 && values(of) && (
                                <span className="text-xs text-secondary">
                                    {percent(step.value, values(of)!)} of {steps[of].label.toLowerCase()}
                                </span>
                            )}
                        </div>
                    )
                })}
            </div>
        )
    }

    return (
        <ol className="m-0 p-0 list-none flex flex-col gap-2">
            {steps.map((step, index) => {
                const previous = index > 0 ? values(step.of ?? index - 1) : null
                return (
                    <li
                        key={step.label}
                        className={
                            layout === 'bars' ? 'grid grid-cols-[10rem_1fr_7rem] items-center gap-3' : 'flex flex-col'
                        }
                    >
                        <span className="text-sm">{step.label}</span>
                        {layout === 'bars' && (
                            <div className="h-6 rounded bg-surface-secondary overflow-hidden">
                                {step.value !== null && (
                                    <div
                                        className="h-full rounded bg-accent"
                                        style={{ width: `${Math.max(1, (step.value / data.sent) * 100)}%` }}
                                    />
                                )}
                            </div>
                        )}
                        <span className={layout === 'bars' ? 'text-right' : 'flex items-baseline gap-2'}>
                            <StepValue step={step} />
                            {step.value !== null && previous ? (
                                <span className="text-xs text-secondary block">
                                    {percent(step.value, previous)}
                                    {step.of !== undefined ? ` of ${steps[step.of].label.toLowerCase()}` : ''}
                                </span>
                            ) : null}
                        </span>
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
    const missing = <span className="text-sm text-secondary">{step.missing}</span>
    return step.missingDetail ? (
        <Tooltip title={step.missingDetail}>
            <span className="underline decoration-dotted cursor-help">{missing}</span>
        </Tooltip>
    ) : (
        missing
    )
}
