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
        <div className="@container/wizard-install">
            <div className="grid grid-cols-1 items-start gap-6 @min-[44rem]/wizard-install:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
                <div className="min-w-0 space-y-6" data-attr="wizard-install-instructions">
                    {children}
                </div>
                <div className="min-w-0">
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
                </div>
            </div>
        </div>
    )
}
