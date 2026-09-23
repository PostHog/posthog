import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { sceneLogic } from 'scenes/sceneLogic'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { wizardRunIsActive } from '../wizardRunDisplay'
import { WizardRunSyncCard, WizardRunSyncLauncher } from './WizardRunSyncCard'
import { WizardRunSyncDetailsDialog } from './WizardRunSyncDetailsDialog'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'

export function WizardRunSyncProject({ projectId }: { projectId: string }): JSX.Element {
    const logic = wizardRunSyncLogic({ projectId })
    useMountedLogic(logic)
    const { activeCount, run, tasks } = useValues(logic)
    const { dismissRun } = useActions(logic)
    const { sceneKey } = useValues(sceneLogic)
    const [dialogRun, setDialogRun] = useState<WizardRunApi | null>(null)
    const [minimizedRunId, setMinimizedRunId] = useState<string | null>(null)
    const [now, setNow] = useState(Date.now)
    useInterval(() => setNow(Date.now()), run && wizardRunIsActive(run) ? 1000 : null)

    const endMs = run?.finished_at ? new Date(run.finished_at).getTime() : now
    const elapsedSeconds = run ? elapsedSecondsFrom(run.started_at ?? run.created_at, endMs) : 0

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
            {run && (
                <div className="fixed bottom-5 right-5 z-[60] max-w-[calc(100vw-2.5rem)]">
                    {minimizedRunId === run.id ? (
                        <WizardRunSyncLauncher
                            run={run}
                            elapsedSeconds={elapsedSeconds}
                            onRestore={() => setMinimizedRunId(null)}
                        />
                    ) : (
                        <WizardRunSyncCard
                            run={run}
                            tasks={tasks}
                            activeCount={activeCount}
                            elapsedSeconds={elapsedSeconds}
                            onExpand={openDetails}
                            onDismiss={() => (wizardRunIsActive(run) ? setMinimizedRunId(run.id) : dismissRun())}
                            dismissTooltip={wizardRunIsActive(run) ? 'Minimize' : 'Dismiss'}
                        />
                    )}
                </div>
            )}
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
