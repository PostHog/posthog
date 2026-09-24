import { useActions, useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { useInterval } from 'lib/hooks/useInterval'
import { elapsedSecondsFrom } from 'lib/utils/datetime'
import { sceneLogic } from 'scenes/sceneLogic'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { wizardRunIsActive } from '../wizardRunDisplay'
import { WizardRunSyncCard } from './WizardRunSyncCard'
import { WizardRunSyncDetailsDialog } from './WizardRunSyncDetailsDialog'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'
import { WizardRunSyncRunPicker } from './WizardRunSyncRunPicker'

export function WizardRunSyncProject({ projectId }: { projectId: string }): JSX.Element {
    const logic = wizardRunSyncLogic({ projectId })
    useMountedLogic(logic)
    const { activeCount, visibleRuns, closedRunIds, dismissedRunIds, run, tasks } = useValues(logic)
    const { closeRun, dismissRun, selectRun: selectSyncRun } = useActions(logic)
    const { sceneKey } = useValues(sceneLogic)
    const [dialogRun, setDialogRun] = useState<WizardRunApi | null>(null)
    const [now, setNow] = useState(Date.now)
    const runHidden = run && (closedRunIds.includes(run.id) || dismissedRunIds.includes(run.id))
    useInterval(() => setNow(Date.now()), run && !runHidden && wizardRunIsActive(run) ? 1000 : null)

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
            {run && !runHidden && (
                <div className="fixed bottom-5 right-5 z-[60] max-w-[calc(100vw-2.5rem)]">
                    <WizardRunSyncCard
                        run={run}
                        tasks={tasks}
                        elapsedSeconds={elapsedSeconds}
                        runPicker={
                            (activeCount > 1 || visibleRuns.length > 1) && (
                                <WizardRunSyncRunPicker
                                    runs={visibleRuns}
                                    activeCount={activeCount}
                                    currentRunId={run.id}
                                    onSelect={selectSyncRun}
                                />
                            )
                        }
                        onExpand={openDetails}
                        onClose={() => closeRun(run.id)}
                        onHide={() => {
                            dismissRun(run.id)
                            lemonToast.info('You can still follow this run on the Wizard page.')
                        }}
                    />
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
