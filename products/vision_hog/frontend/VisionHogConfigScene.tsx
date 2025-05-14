import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

// import { useActions, useValues } from 'kea' // Uncomment if you use actions/values from logic
import { visionHogConfigLogic } from './visionHogConfiglogic'

export const scene: SceneExport = {
    component: VisionHogConfigScene,
    logic: visionHogConfigLogic,
}

export function VisionHogConfigScene(): JSX.Element {
    // const { isLoadingTempBackend, tempBackendData, tempBackendError } = useValues(someLogic)
    // const { loadTempBackendData } = useActions(someLogic)
    const { getConfigSuggestion } = useActions(visionHogConfigLogic)

    return (
        <div>
            <h1>This is a placeholder scene for the VisionHog config.</h1>
            <LemonButton onClick={() => getConfigSuggestion()}>Get config suggestion</LemonButton>
        </div>
    )
}
