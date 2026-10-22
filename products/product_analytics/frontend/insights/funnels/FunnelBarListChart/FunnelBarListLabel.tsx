import clsx from 'clsx'

import { IconInfinity } from '@posthog/icons'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'

import { type FunnelStepWithConversionMetrics } from '~/types'

import { DuplicateStepIndicator } from '../FunnelBarHorizontalChart/DuplicateStepIndicator'
import { FunnelStepMore } from '../shared/FunnelStepMore'
import { getActionFilterFromFunnelStep } from '../shared/funnelStepTableUtils'

export interface FunnelBarListLabelProps {
    step: FunnelStepWithConversionMetrics
    previousStep?: FunnelStepWithConversionMetrics
    stepIndex: number
    period?: 'current' | 'previous'
    isUnordered: boolean
    isOptional: boolean
}

export function FunnelBarListLabel({
    step,
    previousStep,
    stepIndex,
    period,
    isUnordered,
    isOptional,
}: FunnelBarListLabelProps): JSX.Element {
    if (period === 'previous') {
        // Lines up with the step name after the 23px glyph and the 6px cell gap.
        return <span className="truncate pl-[29px] text-secondary">Previous period</span>
    }
    const isDuplicate = !isUnordered && !!previousStep && step.action_id === previousStep.action_id
    return (
        <>
            <span className="shrink-0 select-none">
                <SeriesGlyph variant="funnel-step-glyph">
                    {isUnordered ? <IconInfinity className="w-3.5 fill-[var(--primary_alt)]" /> : step.order + 1}
                </SeriesGlyph>
            </span>
            <span className={clsx('min-w-0 truncate font-semibold', isOptional && 'opacity-60')}>
                {isUnordered ? (
                    `Completed ${step.order + 1} steps`
                ) : (
                    <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
                )}
            </span>
            {isOptional ? <span className="shrink-0 text-secondary @max-md:hidden">(optional)</span> : null}
            {isDuplicate ? <DuplicateStepIndicator /> : null}
            <FunnelStepMore stepIndex={stepIndex} />
        </>
    )
}
