import { useActions, useMountedLogic, useValues } from 'kea'

import { QuillCloudEnvironmentSelect } from '../../../components/quill/QuillCloudEnvironmentSelect'
import { composerSandboxEnvironmentsLogic } from '../composerSandboxEnvironmentsLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

export function TaskComposerEnvironmentSelect(): JSX.Element {
    const panelId = useMountedLogic(taskTrackerSceneLogic).props.panelId
    const { createEnvironment } = useActions(composerSandboxEnvironmentsLogic({ panelId }))
    const { selectedCloudTarget, favoriteCloudTarget, sandboxEnvironments, customImages, isSubmittingTask } =
        useValues(taskTrackerSceneLogic)
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
            disabled={isSubmittingTask}
        />
    )
}
