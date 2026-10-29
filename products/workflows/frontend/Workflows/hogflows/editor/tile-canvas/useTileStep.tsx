import { useValues } from 'kea'
import { useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { stepKindName } from '../../workflowStepCatalog'
import { type TileStep, tileStep } from './tileStep'

export function useTileStep(action: HogFlowAction, workflow: HogFlow): TileStep {
    const { hogFunctionTemplatesById } = useValues(workflowLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(
        () =>
            tileStep(action, workflow, {
                templatesById: hogFunctionTemplatesById,
                isDarkModeOn,
                kindName: stepKindName(action),
            }),
        [action, workflow, hogFunctionTemplatesById, isDarkModeOn]
    )
}
