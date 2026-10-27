import clsx from 'clsx'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { type FunnelStepWithConversionMetrics } from '~/types'

import { FunnelStepPathLinks } from '../shared/FunnelStepPathLinks'
import { getActionFilterFromFunnelStep } from '../shared/funnelStepTableUtils'

export interface FunnelBarListLabelProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    period?: 'current' | 'previous'
    isUnordered: boolean
    isOptional: boolean
    showStepPaths: boolean
}

export function FunnelBarListLabel({
    step,
    stepIndex,
    period,
    isUnordered,
    isOptional,
    showStepPaths,
}: FunnelBarListLabelProps): JSX.Element {
    if (period === 'previous') {
        return <span className="truncate text-secondary">Previous period</span>
    }
    const name = isUnordered ? (
        `Completed ${step.order + 1} steps`
    ) : (
        <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} />
    )
    const nameClassName = clsx(
        '-ml-1 min-w-0 truncate px-1 text-sm leading-4 font-semibold',
        isOptional && 'opacity-60'
    )
    return (
        <>
            {showStepPaths ? (
                <LemonDropdown
                    overlay={<FunnelStepPathLinks stepIndex={stepIndex} />}
                    placement="bottom-start"
                    actionable
                >
                    <button
                        type="button"
                        className={clsx(
                            nameClassName,
                            'cursor-pointer rounded text-left hover:bg-fill-button-tertiary-hover'
                        )}
                        aria-haspopup="menu"
                        data-attr="funnel-step-paths-menu"
                    >
                        {name}
                    </button>
                </LemonDropdown>
            ) : (
                <span className={nameClassName}>{name}</span>
            )}
            {isOptional ? <span className="shrink-0 text-secondary @max-sm:hidden">(optional)</span> : null}
        </>
    )
}
