import { useValues } from 'kea'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { getHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowAction } from '../types'
import { StepCatalogEntry } from './stepCatalog'
import { stepPickerLogic } from './stepPickerLogic'

export function StepPickerStepIcon({ entry, size }: { entry: StepCatalogEntry; size: 'md' | 'lg' }): JSX.Element {
    const { templatesById } = useValues(stepPickerLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const step = getHogFlowStep(entry.action as HogFlowAction, templatesById, isDarkModeOn)

    return (
        <span
            className={`flex shrink-0 items-center justify-center ${size === 'lg' ? 'size-10 text-3xl' : 'size-7 text-xl'}`}
            style={{ color: step?.color }}
        >
            {step?.icon}
        </span>
    )
}
