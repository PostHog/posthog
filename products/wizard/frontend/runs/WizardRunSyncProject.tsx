import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { WizardRunSyncCard } from './WizardRunSyncCard'
import { WizardRunSyncDetailsDialog } from './WizardRunSyncDetailsDialog'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'

export function WizardRunSyncProject({ projectId }: { projectId: string }): JSX.Element {
    const logic = wizardRunSyncLogic({ projectId })
    useMountedLogic(logic)
    const { activeCount, run, tasks } = useValues(logic)
    const { sceneKey } = useValues(sceneLogic)
    const [dialogRun, setDialogRun] = useState<WizardRunApi | null>(null)

    const openDetails = (): void => {
        if (!run) {
            return
        }
        if (sceneKey === 'wizardRuns') {
            wizardRunDetailsLogic.actions.selectRun(run)
        } else {
            setDialogRun(run)
        }
    }

    return (
        <>
            {run && <WizardRunSyncCard run={run} tasks={tasks} activeCount={activeCount} onOpen={openDetails} />}
            {dialogRun && (
                <WizardRunSyncDetailsDialog
                    run={dialogRun}
                    tasks={dialogRun.id === run?.id ? tasks : []}
                    onClose={() => setDialogRun(null)}
                />
            )}
        </>
    )
}
