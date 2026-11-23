import { useActions, useValues } from 'kea'

import { IconListCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutDetailActionsLogic } from '../../../logics/scoutDetailActionsLogic'

export function ScoutRubricsButton({ config }: { config: SignalScoutConfigApi }): JSX.Element | null {
    const logic = scoutDetailActionsLogic({ skillName: config.skill_name })
    const { canEditRubrics } = useValues(logic)
    const { openDialog } = useActions(logic)

    if (!canEditRubrics) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconListCheck />}
            onClick={() => openDialog('rubrics')}
            data-attr="scout-rubrics-open"
        >
            Rubrics
        </LemonButton>
    )
}
