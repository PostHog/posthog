import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { userLogic } from 'scenes/userLogic'

import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { WizardRunSidebarPanel } from './components/WizardRunSidebarPanel'
import { WizardRailButtonView } from './WizardRailButtonView'
import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

export function WizardRailButton({ projectId }: { projectId: string }): JSX.Element | null {
    const { tasksByRunId } = useValues(wizardRunSyncLogic({ projectId }))
    const { user } = useValues(userLogic)
    const sidebarLogic = wizardRunSidebarLogic({ projectId, userId: user?.id ?? 0 })
    const { visibleRuns, runDetectedSources, railVisible, railState, railProgress } = useValues(sidebarLogic)
    const { clickState, clickDetectedSource, dismissRuns, markRunsSeen } = useActions(sidebarLogic)
    const [open, setOpen] = useState(false)

    if (!railVisible) {
        return null
    }

    return (
        <WizardRailButtonView
            state={railState}
            progress={railProgress}
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (nextOpen) {
                    clickState('today_rail')
                    markRunsSeen()
                }
            }}
            panel={
                <WizardRunSidebarPanel
                    runs={visibleRuns}
                    tasksByRunId={tasksByRunId}
                    onDismissRuns={dismissRuns}
                    onNavigate={() => setOpen(false)}
                    detectedSources={runDetectedSources}
                    onDetectedSourceClick={clickDetectedSource}
                />
            }
        />
    )
}
