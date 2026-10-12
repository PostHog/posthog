import './FunnelBarVertical.scss'

import { useValues } from 'kea'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { FunnelStepPathLinks } from '../shared/FunnelStepPathLinks'
import { getActionFilterFromFunnelStep } from '../shared/funnelStepTableUtils'

type StepNameLabelProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}

export function StepNameLabel({ step, stepIndex }: StepNameLabelProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isStepOptional, querySource } = useValues(funnelDataLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const isOptionalStep = isStepOptional(stepIndex + 1)
    // Paths are user-based, so there is nothing to link to when aggregating by groups.
    const hasPathLinks =
        hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && querySource?.aggregation_group_type_index == null

    const name = (
        <span className="StepNameLabel__name font-semibold leading-5">
            <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap />
            {isOptionalStep ? <span className="ml-1 text-xs font-normal">(optional)</span> : null}
        </span>
    )

    return (
        <div
            className="StepNameLabel flex items-start justify-center px-1 text-center text-sm"
            data-attr="funnel-step-legend"
            style={{ opacity: isOptionalStep ? 0.6 : 1 }}
        >
            {hasPathLinks ? (
                <LemonDropdown overlay={<FunnelStepPathLinks stepIndex={stepIndex} />} placement="bottom" actionable>
                    <button
                        type="button"
                        className="max-w-full cursor-pointer rounded px-1 hover:bg-fill-button-tertiary-hover"
                        aria-haspopup="menu"
                        data-attr="funnel-step-paths-menu"
                    >
                        {name}
                    </button>
                </LemonDropdown>
            ) : (
                <div className="max-w-full px-1">{name}</div>
            )}
        </div>
    )
}
