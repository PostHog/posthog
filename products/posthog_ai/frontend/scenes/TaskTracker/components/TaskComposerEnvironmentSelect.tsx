import { useActions, useMountedLogic, useValues } from 'kea'

import { cloudEnvironmentsLogic } from 'scenes/settings/environment/cloudEnvironmentsLogic'

import { QuillCloudEnvironmentSelect } from '../../../components/quill/QuillCloudEnvironmentSelect'
import { composerSandboxEnvironmentsLogic } from '../composerSandboxEnvironmentsLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

export function TaskComposerEnvironmentSelect(): JSX.Element {
    const panelId = useMountedLogic(taskTrackerSceneLogic).props.panelId
    const composerEnvironments = composerSandboxEnvironmentsLogic({ panelId })
    const { createEnvironment, retryCloudTargets } = useActions(composerEnvironments)
    const { imagesFailed, imagesLoading, awaitingCreatedEnvironment } = useValues(composerEnvironments)
    const { environmentsLoading, environmentsFailed } = useValues(cloudEnvironmentsLogic)
    const {
        selectedCloudTarget,
        favoriteCloudTarget,
        sandboxEnvironments,
        customImages,
        isSubmittingTask,
        defaultCloudTargetSaving,
        taskDefaults,
    } = useValues(taskTrackerSceneLogic)
    const { pickCloudTarget, toggleFavoriteCloudTarget } = useActions(taskTrackerSceneLogic)

    return (
        <QuillCloudEnvironmentSelect
            value={selectedCloudTarget}
            favorite={favoriteCloudTarget}
            environments={sandboxEnvironments}
            images={customImages}
            onChange={pickCloudTarget}
            onToggleFavorite={toggleFavoriteCloudTarget}
            onCreate={createEnvironment}
            onRetry={retryCloudTargets}
            loading={(environmentsLoading && !sandboxEnvironments) || (imagesLoading && !customImages)}
            failed={environmentsFailed || imagesFailed}
            favoriteSaving={defaultCloudTargetSaving || !taskDefaults}
            ownsEnvironmentForm={awaitingCreatedEnvironment}
            disabled={isSubmittingTask}
        />
    )
}
