import clsx from 'clsx'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { FunnelsQuery } from '~/queries/schema/schema-general'
import { type FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepMore } from '../shared/FunnelStepMore'
import { getFunnelStepEntity, getFunnelStepSeries, isRepeatedFunnelStep } from '../shared/funnelStepSeries'
import { DuplicateStepIndicator } from './DuplicateStepIndicator'

interface StepHeaderProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    /** The step immediately before this one, for duplicate-step detection. */
    previousStep: FunnelStepWithConversionMetrics | undefined
    querySource: FunnelsQuery | null
    isUnordered: boolean
    isOptional: boolean
}

export function StepHeader({
    step,
    stepIndex,
    previousStep,
    querySource,
    isUnordered,
    isOptional,
}: StepHeaderProps): JSX.Element {
    const showMedianTime = step.median_conversion_time != null && step.median_conversion_time >= Number.EPSILON
    const isRepeatedStep =
        !isUnordered &&
        previousStep != null &&
        isRepeatedFunnelStep(
            getFunnelStepSeries(querySource, stepIndex, step),
            getFunnelStepSeries(querySource, stepIndex - 1, previousStep)
        )

    return (
        <div className={clsx('flex flex-wrap items-center justify-between leading-5', isOptional && 'opacity-60')}>
            <div className="flex items-center max-w-full grow">
                <div className="overflow-hidden font-bold break-words whitespace-normal">
                    {isUnordered ? (
                        <span>Completed {step.order + 1} steps</span>
                    ) : (
                        <EntityFilterInfo filter={getFunnelStepEntity(querySource, stepIndex, step)} allowWrap />
                    )}
                </div>
                {isOptional ? <div className="ml-1 text-xs">(optional)</div> : null}
                {isRepeatedStep && <DuplicateStepIndicator />}
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
