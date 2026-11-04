import { useActions, useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'
import { WizardRunSidebarWidgetView } from './WizardRunSidebarWidgetView'

export function WizardRunSidebarWidget({ projectId }: { projectId: string }): JSX.Element | null {
    const logic = wizardRunSyncLogic({ projectId })
    const { tasksByRunId } = useValues(logic)
    const { user } = useValues(userLogic)
    const sidebarLogic = wizardRunSidebarLogic({ projectId, userId: user?.id ?? 0 })
    const { visibleRuns } = useValues(sidebarLogic)
    const { clickState, dismissRuns } = useActions(sidebarLogic)
    return (
        <WizardRunSidebarWidgetView
            key={`${projectId}.${user?.id}`}
            runs={visibleRuns}
            tasksByRunId={tasksByRunId}
            onStateClick={clickState}
            onDismissRuns={dismissRuns}
        />
    )
}
