import { useValues } from 'kea'
import { Fragment, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { getHogFlowStep } from '../hogflows/steps/HogFlowSteps'
import type { HogFlowAction } from '../hogflows/types'

const MAX_VISIBLE_STEPS = 4

/** The steps of a workflow template, drawn as the same icon tiles the editor canvas uses. */
export function WorkflowTemplateSteps({ actions }: { actions: HogFlowAction[] }): JSX.Element | null {
    const { isDarkModeOn } = useValues(themeLogic)

    const steps = useMemo(
        () =>
            actions
                // The exit step closes every workflow, so it says nothing about this one
                .filter((action) => action.type !== 'exit')
                .map((action) => getHogFlowStep(action, {}, isDarkModeOn))
                .filter((step) => !!step),
        [actions, isDarkModeOn]
    )

    if (steps.length === 0) {
        return null
    }

    const visibleSteps = steps.slice(0, MAX_VISIBLE_STEPS)
    const hiddenStepCount = steps.length - visibleSteps.length

    return (
        <div className="flex items-center">
            {visibleSteps.map((step, index) => (
                <Fragment key={index}>
                    {index > 0 && <StepConnector />}
                    <div
                        className="flex items-center justify-center rounded size-6 shrink-0"
                        style={{ backgroundColor: `${step.color}20`, color: step.color }}
                    >
                        {step.icon}
                    </div>
                </Fragment>
            ))}
            {hiddenStepCount > 0 && (
                <>
                    <StepConnector />
                    <div className="flex items-center justify-center rounded h-6 px-1.5 shrink-0 text-xs text-secondary bg-fill-primary">
                        +{hiddenStepCount}
                    </div>
                </>
            )}
        </div>
    )
}

function StepConnector(): JSX.Element {
    return <div className="w-2 shrink-0 border-t border-dashed" />
}
