import { useAsyncActions, useValues } from 'kea'

import { LemonButton, LemonButtonPropsBase } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { teamLogic } from 'scenes/teamLogic'

import { confirmMoveStartDate } from '../experimentActions'
import type { HealthPanelFinding } from './healthPanelFindings'

export function HealthMoveStartDateButton({
    evidence,
    buttonProps,
    onClick,
}: {
    evidence: HealthPanelFinding['evidence']
    buttonProps: Pick<LemonButtonPropsBase, 'size' | 'type' | 'data-attr' | 'disabledReason'>
    onClick: () => void
}): JSX.Element | null {
    const { experiment, experimentUpdateLoading } = useValues(experimentLogic)
    const { changeExperimentStartDate } = useAsyncActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)

    const currentStartDate = experiment.start_date
    const suggestedStartDate = evidence.suggested_start_date
    if (!currentStartDate || typeof suggestedStartDate !== 'string') {
        return null
    }
    return (
        <LemonButton
            {...buttonProps}
            disabledReason={buttonProps.disabledReason || (experimentUpdateLoading ? 'Saving the experiment...' : null)}
            onClick={() => {
                onClick()
                confirmMoveStartDate({
                    currentStartDate,
                    newStartDate: suggestedStartDate,
                    projectTimezone: currentTeam?.timezone ?? 'UTC',
                    onConfirm: () => changeExperimentStartDate(suggestedStartDate),
                })
            }}
        >
            Move start date
        </LemonButton>
    )
}
