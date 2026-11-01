import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { StepImportNotesBadge } from './StepImportNotesBadge'
import { StepImportNotesList } from './StepImportNotesList'
import { workflowImportNotesLogic } from './workflowImportNotesLogic'

/** The import badge with its notes on hover, for steps that have no hover card of their own. */
export function StepImportNotesTooltipBadge({
    workflowId,
    stepId,
}: {
    workflowId: string
    stepId: string
}): JSX.Element | null {
    const { notesByStepId } = useValues(workflowImportNotesLogic({ id: workflowId }))
    if (!notesByStepId[stepId]?.length) {
        return null
    }
    return (
        <Tooltip title={<StepImportNotesList workflowId={workflowId} stepId={stepId} />}>
            <span>
                <StepImportNotesBadge workflowId={workflowId} stepId={stepId} />
            </span>
        </Tooltip>
    )
}
