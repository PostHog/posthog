import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import type { WizardRunApi } from '../../generated/api.schemas'
import { wizardRunDetailsLogic } from '../../logics/wizardRunDetailsLogic'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { WizardRunDetailsDialog } from './WizardRunDetailsDialog'

export function WizardRunSceneSyncDetailsDialog({
    projectId,
    onRunAgain,
}: {
    projectId: string
    onRunAgain: (run: WizardRunApi) => void
}): JSX.Element {
    const { tasksByRunId } = useValues(wizardRunSyncLogic({ projectId }))
    const { loadRunData, watchRuns } = useActions(wizardRunSyncLogic({ projectId }))
    const { selectedRun } = useValues(wizardRunDetailsLogic)
    useEffect(() => {
        watchRuns('run-details', selectedRun ? [selectedRun.id] : [])
        if (selectedRun) {
            loadRunData(selectedRun)
        }
        return () => watchRuns('run-details', [])
    }, [selectedRun, loadRunData, watchRuns])

    return (
        <WizardRunDetailsDialog
            tasks={selectedRun ? (tasksByRunId[selectedRun.id] ?? []) : []}
            onRunAgain={onRunAgain}
        />
    )
}
