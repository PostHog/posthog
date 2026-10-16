import './FunnelBarVertical.scss'

import { useActions, useValues } from 'kea'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { FunnelStepPathLinks } from '../shared/FunnelStepPathLinks'
import { getActionFilterFromFunnelStep } from '../shared/funnelStepTableUtils'
import { ValueInspectorButton } from '../shared/ValueInspectorButton'

type StepNameLabelProps = {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showPersonsModal: boolean
}

export function StepNameLabel({ step, stepIndex, showPersonsModal }: StepNameLabelProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isStepOptional, querySource, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { isInExperimentContext } = useValues(funnelPersonsModalLogic(insightProps))
    const { openPersonsModalForStep } = useActions(funnelPersonsModalLogic(insightProps))
    const { hasAvailableFeature } = useValues(userLogic)

    const isOptionalStep = isStepOptional(stepIndex + 1)
    // Paths are user-based, so there is nothing to link to when aggregating by groups.
    const hasPathLinks =
        hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && querySource?.aggregation_group_type_index == null

    const name = (
        <span className="StepNameLabel__name font-semibold leading-5">
            <EntityFilterInfo filter={getActionFilterFromFunnelStep(step)} allowWrap showSingleName />
            {isOptionalStep ? <span className="ml-1 text-xs font-normal">(optional)</span> : null}
        </span>
    )

    const count = step.count ?? 0
    const countLabel = (
        <span className="tabular-nums">
            <span translate="no">{humanFriendlyNumber(count)}</span>
            <span className="hidden @min-[11rem]:inline">
                {` ${pluralize(count, aggregationTargetLabel.singular, aggregationTargetLabel.plural, false)}`}
            </span>
        </span>
    )

    return (
        <div
            className="StepNameLabel flex flex-col items-center px-1 text-center text-sm"
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
            <Tooltip title={`${capitalizeFirstLetter(aggregationTargetLabel.plural)} who completed this step`}>
                {showPersonsModal && !isInExperimentContext ? (
                    <ValueInspectorButton
                        onClick={() => openPersonsModalForStep({ step, stepIndex, converted: true })}
                        // pinned: shared with the legacy step legend, so autocapture insights keep counting clicks
                        data-attr="funnel-inspect-converted"
                    >
                        {countLabel}
                    </ValueInspectorButton>
                ) : (
                    <span className="text-secondary">{countLabel}</span>
                )}
            </Tooltip>
        </div>
    )
}
