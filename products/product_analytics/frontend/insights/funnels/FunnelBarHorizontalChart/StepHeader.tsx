import clsx from 'clsx'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { DuplicateStepIndicator } from 'scenes/funnels/FunnelBarHorizontal/DuplicateStepIndicator'
import { FunnelStepMore } from 'scenes/funnels/FunnelStepMore'
import { getActionFilterFromFunnelStep } from 'scenes/insights/views/Funnels/funnelStepTableUtils'

import { type FunnelStepWithConversionMetrics } from '~/types'

interface StepHeaderProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    /** The step immediately before this one, for duplicate-step detection. */
    previousStep: FunnelStepWithConversionMetrics | undefined
    isUnordered: boolean
    isOptional: boolean
}

export function StepHeader({ step, stepIndex, previousStep, isUnordered, isOptional }: StepHeaderProps): JSX.Element {
    const showMedianTime = step.median_conversion_time != null && step.median_conversion_time >= Number.EPSILON

    return (
        <div className={clsx('flex flex-wrap items-center justify-between leading-5', isOptional && 'opacity-60')}>
            <div className="flex items-center max-w-full grow">
                {/* `wrap-anywhere`, so an event name with no spaces wraps instead of getting cut off. */}
                <div className="overflow-hidden font-bold wrap-anywhere whitespace-normal">
                    {isUnordered ? (
                        <span>Completed {step.order + 1} steps</span>
                    ) : (
                        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
                    )}
                </div>
                {isOptional ? <div className="ml-1 text-xs">(optional)</div> : null}
                {!isUnordered && previousStep != null && step.action_id === previousStep.action_id && (
                    <DuplicateStepIndicator />
                )}
                <FunnelStepMore stepIndex={stepIndex} className="ml-1" />
            </div>
            {showMedianTime ? (
                <div className="text-secondary text-xs" title="Median time of conversion from previous step">
                    Median time: <b>{humanFriendlyDuration(step.median_conversion_time, { maxUnits: 2 })}</b>
                </div>
            ) : null}
        </div>
    )
}
