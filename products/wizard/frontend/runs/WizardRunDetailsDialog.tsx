import { useActions, useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { WizardRunDetailsDrawer } from './WizardRunDetailsDrawer'

export function WizardRunDetailsDialog({
    onRunAgain,
    onClose,
    tasks = [],
}: {
    onRunAgain?: (run: WizardRunApi) => void
    onClose?: () => void
    tasks?: readonly WizardRunTaskApi[]
}): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        cancelRunRequestLoading,
        runArtifactsError,
        runDetailsError,
        runDetailsLoading,
        runDiffError,
        runDiffLoading,
        selectedRun,
        selectedRunArtifacts,
        selectedRunArtifactsInitialLoading,
        selectedRunDiffArtifactId,
        selectedRunDiffContent,
    } = useValues(wizardRunDetailsLogic)
    const { artifactClicked, cancelRun, closeRunDiff, copyRunId, openRunDiff, refreshSelectedRun, selectRun } =
        useActions(wizardRunDetailsLogic)

    return (
        <WizardRunDetailsDrawer
            run={selectedRun}
            tasks={tasks}
            artifacts={selectedRunArtifacts}
            artifactsError={runArtifactsError}
            artifactsLoading={selectedRunArtifactsInitialLoading}
            currentUserId={user?.id ?? null}
            detailsError={runDetailsError}
            refreshing={runDetailsLoading}
            cancelling={cancelRunRequestLoading}
            diffArtifactId={selectedRunDiffArtifactId}
            diffContent={selectedRunDiffContent}
            diffError={runDiffError}
            diffLoading={runDiffLoading}
            onClose={() => {
                selectRun(null)
                onClose?.()
            }}
            onCloseDiff={closeRunDiff}
            onOpenDiff={openRunDiff}
            onArtifactClick={artifactClicked}
            onRefresh={refreshSelectedRun}
            onCopyRunId={copyRunId}
            onCancel={cancelRun}
            onRunAgain={onRunAgain}
        />
    )
}
