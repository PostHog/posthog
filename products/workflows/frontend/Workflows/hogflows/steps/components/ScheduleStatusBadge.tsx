import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { workflowLogic } from '../../../workflowLogic'

export function ScheduleStatusBadge(): JSX.Element | null {
    const { currentSchedule, workflow } = useValues(workflowLogic)

    if (!currentSchedule) {
        return null
    }

    const isWorkflowActive = workflow?.status === 'active'
    const isCompleted = currentSchedule.status === 'completed'
    const isSchedulePaused = currentSchedule.status === 'paused'

    if (isCompleted) {
        return (
            <LemonTag type="default" size="small">
                Completed
            </LemonTag>
        )
    }

    if (isSchedulePaused || !isWorkflowActive) {
        return (
            <LemonTag type="warning" size="small">
                Paused
            </LemonTag>
        )
    }

    return (
        <LemonTag type="success" size="small">
            Active
        </LemonTag>
    )
}
