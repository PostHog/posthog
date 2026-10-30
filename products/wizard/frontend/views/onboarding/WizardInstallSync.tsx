import { useActions, useValues } from 'kea'
import { ReactNode, useState } from 'react'

import { useInterval } from 'lib/hooks/useInterval'
import { userLogic } from 'scenes/userLogic'

import { wizardRunIsActive } from '../../lib/wizardRunDisplay'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { onboardingWizardRunLogic } from './onboardingWizardRunLogic'
import { WizardInstallSyncView } from './WizardInstallSyncView'

export function WizardInstallSync({
    projectId,
    children,
}: {
    projectId: string | null
    children: ReactNode
}): JSX.Element {
    const { user } = useValues(userLogic)
    const scopedProjectId = projectId ?? ''
    const onboardingLogic = onboardingWizardRunLogic({ projectId: scopedProjectId, userId: user?.id ?? 0 })
    const { run } = useValues(onboardingLogic)
    const { clickArtifact } = useActions(onboardingLogic)
    const syncLogic = wizardRunSyncLogic({ projectId: scopedProjectId })
    const { tasksByRunId, artifactsByRunId, runDataErrors, runDataLoading } = useValues(syncLogic)
    const { loadRunData } = useActions(syncLogic)
    const [now, setNow] = useState(Date.now)
    useInterval(() => setNow(Date.now()), run && wizardRunIsActive(run) ? 1000 : null)

    if (!run) {
        return <>{children}</>
    }
    return (
        <>
            <WizardInstallSyncView
                run={run}
                tasks={tasksByRunId[run.id] ?? []}
                artifacts={artifactsByRunId[run.id] ?? []}
                loading={runDataLoading[run.id] ?? true}
                error={runDataErrors[run.id] ?? null}
                onRetry={() => loadRunData(run, { force: true })}
                onArtifactClick={clickArtifact}
                now={now}
            />
            {(run.status === 'failed' || run.status === 'cancelled') && children}
        </>
    )
}
